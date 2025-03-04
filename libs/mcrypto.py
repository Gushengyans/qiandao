#!/usr/bin/env python
# -*- encoding: utf-8 -*-
# vim: set et sw=4 ts=4 sts=4 ff=unix fenc=utf8:
# Author: Binux<i@binux.me>
#         http://binux.me
# Created on 2014-08-07 21:01:31

import base64
import umsgpack
import config

from pbkdf2 import PBKDF2
from Crypto import Random
from Crypto.Hash import SHA256
from Crypto.Cipher import AES

Crypto_random = Random.new()
def password_hash(word, salt=None, iterations=config.pbkdf2_iterations):
    if salt is None:
        salt = Crypto_random.read(16)
    elif len(salt) > 16:
        _, salt, iterations = umsgpack.unpackb(salt)

    word = umsgpack.packb(word)

    rawhash = PBKDF2(word, salt, iterations).read(32)

    return umsgpack.packb([rawhash, salt, iterations])

def aes_encrypt(word, key=config.aes_key, iv=None):
    if iv is None:
        iv = Crypto_random.read(16)

    word = umsgpack.packb(word)
    mod = len(word) % 16
    if mod != 0:
        word += b'\0' * (16-mod)

    aes = AES.new(key, AES.MODE_CBC, iv)
    ciphertext = aes.encrypt(word)

    return umsgpack.packb([ciphertext, iv])

def aes_decrypt(word, key=config.aes_key, iv=None):
    if iv is None:
        word, iv = umsgpack.unpackb(word)
    else:
        raise Exception('no iv error')

    aes = AES.new(key, AES.MODE_CBC, iv)
    word = aes.decrypt(word)

    while word:
        try:
            return umsgpack.unpackb(word)
        except umsgpack.ExtraData:
            word = word[:-1]


from collections import namedtuple
import random
import re
import string
import sys

from libs.convert import to_bytes, to_text

DEFAULT_PASSWORD_LENGTH = 20
ascii_lowercase = 'abcdefghijklmnopqrstuvwxyz'
ascii_uppercase = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
ascii_letters = ascii_lowercase + ascii_uppercase
digits = '0123456789'
DEFAULT_PASSWORD_CHARS = to_text(ascii_letters + digits + ".,:-_", errors='strict')  # characters included in auto-generated passwords
PASSLIB_E = CRYPT_E = None
HAS_CRYPT = PASSLIB_AVAILABLE = False
try:
    import passlib
    import passlib.hash
    from passlib.utils.handlers import HasRawSalt, PrefixWrapper
    try:
        from passlib.utils.binary import bcrypt64
    except ImportError:
        from passlib.utils import bcrypt64
    PASSLIB_AVAILABLE = True
except Exception as e:
    PASSLIB_E = e

try:
    import Crypto
    HAS_CRYPT = True
except Exception as e:
    CRYPT_E = e
    

def random_password(length=DEFAULT_PASSWORD_LENGTH, chars=DEFAULT_PASSWORD_CHARS, seed=None):
    '''Return a random password string of length containing only chars

    :kwarg length: The number of characters in the new password.  Defaults to 20.
    :kwarg chars: The characters to choose from.  The default is all ascii
        letters, ascii digits, and these symbols ``.,:-_``
    '''
    if not isinstance(chars, str):
        raise Exception('%s (%s) is not a text_type' % (chars, type(chars)))

    if seed is None:
        random_generator = random.SystemRandom()
    else:
        random_generator = random.Random(seed)
    return u''.join(random_generator.choice(chars) for dummy in range(length))


def random_salt(length=8):
    """Return a text string suitable for use as a salt for the hash functions we use to encrypt passwords.
    """
    # Note passlib salt values must be pure ascii so we can't let the user
    # configure this
    salt_chars = string.ascii_letters + string.digits + u'./'
    return random_password(length=length, chars=salt_chars)


class BaseHash(object):
    algo = namedtuple('algo', ['crypt_id', 'salt_size', 'implicit_rounds', 'salt_exact', 'implicit_ident'])
    algorithms = {
        'md5_crypt': algo(crypt_id='1', salt_size=8, implicit_rounds=None, salt_exact=False, implicit_ident=None),
        'bcrypt': algo(crypt_id='2b', salt_size=22, implicit_rounds=12, salt_exact=True, implicit_ident='2b'),
        'sha256_crypt': algo(crypt_id='5', salt_size=16, implicit_rounds=535000, salt_exact=False, implicit_ident=None),
        'sha512_crypt': algo(crypt_id='6', salt_size=16, implicit_rounds=656000, salt_exact=False, implicit_ident=None),
    }

    def __init__(self, algorithm):
        self.algorithm = algorithm

class CryptHash(BaseHash):
    def __init__(self, algorithm):
        super(CryptHash, self).__init__(algorithm)

        if not HAS_CRYPT:
            raise Exception("crypt.crypt cannot be used as the 'crypt' python library is not installed or is unusable.", orig_exc=CRYPT_E)

        if sys.platform.startswith('darwin'):
            raise Exception("crypt.crypt not supported on Mac OS X/Darwin, install passlib python module")

        if algorithm not in self.algorithms:
            raise Exception("crypt.crypt does not support '%s' algorithm" % self.algorithm)
        self.algo_data = self.algorithms[algorithm]

    def hash(self, secret, salt=None, salt_size=None, rounds=None, ident=None):
        salt = self._salt(salt, salt_size)
        rounds = self._rounds(rounds)
        ident = self._ident(ident)
        return self._hash(secret, salt, rounds, ident)

    def _salt(self, salt, salt_size):
        salt_size = salt_size or self.algo_data.salt_size
        ret = salt or random_salt(salt_size)
        if re.search(r'[^./0-9A-Za-z]', ret):
            raise Exception("invalid characters in salt")
        if self.algo_data.salt_exact and len(ret) != self.algo_data.salt_size:
            raise Exception("invalid salt size")
        elif not self.algo_data.salt_exact and len(ret) > self.algo_data.salt_size:
            raise Exception("invalid salt size")
        return ret

    def _rounds(self, rounds):
        if rounds == self.algo_data.implicit_rounds:
            # Passlib does not include the rounds if it is the same as implicit_rounds.
            # Make crypt lib behave the same, by not explicitly specifying the rounds in that case.
            return None
        else:
            return rounds

    def _ident(self, ident):
        if not ident:
            return self.algo_data.crypt_id
        if self.algorithm == 'bcrypt':
            return ident
        return None

    def _hash(self, secret, salt, rounds, ident):
        saltstring = ""
        if ident:
            saltstring = "$%s" % ident

        if rounds:
            saltstring += "$rounds=%d" % rounds

        saltstring += "$%s" % salt

        # crypt.crypt on Python < 3.9 returns None if it cannot parse saltstring
        # On Python >= 3.9, it throws OSError.
        try:
            result = Crypto.crypt(secret, saltstring)
            orig_exc = None
        except OSError as e:
            result = None
            orig_exc = e

        # None as result would be interpreted by the some modules (user module)
        # as no password at all.
        if not result:
            raise Exception(
                "crypt.crypt does not support '%s' algorithm" % self.algorithm,
                orig_exc=orig_exc,
            )

        return result
    
class PasslibHash(BaseHash):
    def __init__(self, algorithm):
        super(PasslibHash, self).__init__(algorithm)

        if not PASSLIB_AVAILABLE:
            raise Exception("passlib must be installed and usable to hash with '%s'" % algorithm, orig_exc=PASSLIB_E)

        try:
            self.crypt_algo = getattr(passlib.hash, algorithm)
        except Exception:
            raise Exception("passlib does not support '%s' algorithm" % algorithm)

    def hash(self, secret, salt=None, salt_size=None, rounds=None, ident=None):
        salt = self._clean_salt(salt)
        rounds = self._clean_rounds(rounds)
        ident = self._clean_ident(ident)
        return self._hash(secret, salt=salt, salt_size=salt_size, rounds=rounds, ident=ident)

    def _clean_ident(self, ident):
        ret = None
        if not ident:
            if self.algorithm in self.algorithms:
                return self.algorithms.get(self.algorithm).implicit_ident
            return ret
        if self.algorithm == 'bcrypt':
            return ident
        return ret

    def _clean_salt(self, salt):
        if not salt:
            return None
        elif issubclass(self.crypt_algo.wrapped if isinstance(self.crypt_algo, PrefixWrapper) else self.crypt_algo, HasRawSalt):
            ret = to_bytes(salt, encoding='ascii', errors='strict')
        else:
            ret = to_text(salt, encoding='ascii', errors='strict')

        # Ensure the salt has the correct padding
        if self.algorithm == 'bcrypt':
            ret = bcrypt64.repair_unused(ret)

        return ret

    def _clean_rounds(self, rounds):
        algo_data = self.algorithms.get(self.algorithm)
        if rounds:
            return rounds
        elif algo_data and algo_data.implicit_rounds:
            # The default rounds used by passlib depend on the passlib version.
            # For consistency ensure that passlib behaves the same as crypt in case no rounds were specified.
            # Thus use the crypt defaults.
            return algo_data.implicit_rounds
        else:
            return None

    def _hash(self, secret, salt, salt_size, rounds, ident):
        # Not every hash algorithm supports every parameter.
        # Thus create the settings dict only with set parameters.
        settings = {}
        if salt:
            settings['salt'] = salt
        if salt_size:
            settings['salt_size'] = salt_size
        if rounds:
            settings['rounds'] = rounds
        if ident:
            settings['ident'] = ident

        # starting with passlib 1.7 'using' and 'hash' should be used instead of 'encrypt'
        if hasattr(self.crypt_algo, 'hash'):
            result = self.crypt_algo.using(**settings).hash(secret)
        elif hasattr(self.crypt_algo, 'encrypt'):
            result = self.crypt_algo.encrypt(secret, **settings)
        else:
            raise Exception("installed passlib version %s not supported" % passlib.__version__)

        # passlib.hash should always return something or raise an exception.
        # Still ensure that there is always a result.
        # Otherwise an empty password might be assumed by some modules, like the user module.
        if not result:
            raise Exception("failed to hash with algorithm '%s'" % self.algorithm)

        # Hashes from passlib.hash should be represented as ascii strings of hex
        # digits so this should not traceback.  If it's not representable as such
        # we need to traceback and then block such algorithms because it may
        # impact calling code.
        return to_text(result, errors='strict')
    
def passlib_or_crypt(secret, algorithm, salt=None, salt_size=None, rounds=None, ident=None):
    if PASSLIB_AVAILABLE:
        return PasslibHash(algorithm).hash(secret, salt=salt, salt_size=salt_size, rounds=rounds, ident=ident)
    if HAS_CRYPT:
        return CryptHash(algorithm).hash(secret, salt=salt, salt_size=salt_size, rounds=rounds, ident=ident)
    raise Exception("Unable to encrypt nor hash, either crypt or passlib must be installed.", orig_exc=CRYPT_E)