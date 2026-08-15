package com.penghanli.pyvpn.protocol;

import java.security.GeneralSecurityException;
import javax.crypto.AEADBadTagException;
import javax.crypto.Cipher;
import javax.crypto.spec.IvParameterSpec;
import javax.crypto.spec.SecretKeySpec;

public final class TunnelCipher {
    private final DirectionKey directionKey;

    public TunnelCipher(DirectionKey directionKey) {
        this.directionKey = directionKey;
    }

    public byte[] encrypt(long sequence, byte[] plaintext, byte[] aad)
            throws PyVpnProtocolException {
        return crypt(Cipher.ENCRYPT_MODE, sequence, plaintext, aad);
    }

    public byte[] decrypt(long sequence, byte[] ciphertext, byte[] aad)
            throws PyVpnProtocolException {
        return crypt(Cipher.DECRYPT_MODE, sequence, ciphertext, aad);
    }

    private byte[] crypt(int mode, long sequence, byte[] input, byte[] aad)
            throws PyVpnProtocolException {
        try {
            Cipher cipher = createCipher();
            SecretKeySpec key = new SecretKeySpec(directionKey.key(), "ChaCha20");
            cipher.init(mode, key, new IvParameterSpec(directionKey.nonce(sequence)));
            cipher.updateAAD(aad);
            return cipher.doFinal(input);
        } catch (AEADBadTagException exception) {
            throw new PyVpnProtocolException("invalid encrypted tunnel packet", exception);
        } catch (GeneralSecurityException exception) {
            throw new PyVpnProtocolException("ChaCha20-Poly1305 is unavailable", exception);
        }
    }

    private static Cipher createCipher() throws GeneralSecurityException {
        try {
            return Cipher.getInstance("ChaCha20/Poly1305/NoPadding");
        } catch (GeneralSecurityException ignored) {
            return Cipher.getInstance("ChaCha20-Poly1305");
        }
    }
}
