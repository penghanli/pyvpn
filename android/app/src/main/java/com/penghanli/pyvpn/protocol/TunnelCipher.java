package com.penghanli.pyvpn.protocol;

import java.security.GeneralSecurityException;
import javax.crypto.AEADBadTagException;
import javax.crypto.Cipher;
import javax.crypto.spec.IvParameterSpec;
import javax.crypto.spec.SecretKeySpec;

public final class TunnelCipher {
    public static final int TAG_SIZE = 16;

    private final DirectionKey directionKey;
    private final SecretKeySpec key;
    private Cipher encryptionCipher;
    private Cipher decryptionCipher;

    public TunnelCipher(DirectionKey directionKey) {
        this.directionKey = directionKey;
        this.key = new SecretKeySpec(directionKey.key(), "ChaCha20");
    }

    public synchronized byte[] encrypt(long sequence, byte[] plaintext, byte[] aad)
            throws PyVpnProtocolException {
        byte[] output = new byte[plaintext.length + TAG_SIZE];
        int written = encryptInto(
                sequence,
                plaintext,
                0,
                plaintext.length,
                aad,
                0,
                aad.length,
                output,
                0
        );
        if (written != output.length) {
            throw new PyVpnProtocolException("unexpected encrypted packet length");
        }
        return output;
    }

    public synchronized int encryptInto(
            long sequence,
            byte[] plaintext,
            int plaintextOffset,
            int plaintextLength,
            byte[] aad,
            int aadOffset,
            int aadLength,
            byte[] output,
            int outputOffset
    ) throws PyVpnProtocolException {
        requireRange(plaintext, plaintextOffset, plaintextLength, "plaintext");
        requireRange(aad, aadOffset, aadLength, "AAD");
        requireRange(output, outputOffset, plaintextLength + TAG_SIZE, "output");
        try {
            Cipher cipher = initializedCipher(Cipher.ENCRYPT_MODE, sequence);
            cipher.updateAAD(aad, aadOffset, aadLength);
            return cipher.doFinal(
                    plaintext,
                    plaintextOffset,
                    plaintextLength,
                    output,
                    outputOffset
            );
        } catch (GeneralSecurityException exception) {
            throw new PyVpnProtocolException("ChaCha20-Poly1305 is unavailable", exception);
        }
    }

    public synchronized byte[] decrypt(long sequence, byte[] ciphertext, byte[] aad)
            throws PyVpnProtocolException {
        return decrypt(
                sequence,
                ciphertext,
                0,
                ciphertext.length,
                aad,
                0,
                aad.length
        );
    }

    public synchronized byte[] decrypt(
            long sequence,
            byte[] ciphertext,
            int ciphertextOffset,
            int ciphertextLength,
            byte[] aad,
            int aadOffset,
            int aadLength
    ) throws PyVpnProtocolException {
        requireRange(ciphertext, ciphertextOffset, ciphertextLength, "ciphertext");
        requireRange(aad, aadOffset, aadLength, "AAD");
        try {
            Cipher cipher = initializedCipher(Cipher.DECRYPT_MODE, sequence);
            cipher.updateAAD(aad, aadOffset, aadLength);
            return cipher.doFinal(ciphertext, ciphertextOffset, ciphertextLength);
        } catch (AEADBadTagException exception) {
            throw new PyVpnProtocolException("invalid encrypted tunnel packet", exception);
        } catch (GeneralSecurityException exception) {
            throw new PyVpnProtocolException("ChaCha20-Poly1305 is unavailable", exception);
        }
    }

    public synchronized int decryptInto(
            long sequence,
            byte[] ciphertext,
            int ciphertextOffset,
            int ciphertextLength,
            byte[] aad,
            int aadOffset,
            int aadLength,
            byte[] output,
            int outputOffset
    ) throws PyVpnProtocolException {
        requireRange(ciphertext, ciphertextOffset, ciphertextLength, "ciphertext");
        requireRange(aad, aadOffset, aadLength, "AAD");
        requireRange(output, outputOffset, ciphertextLength, "output");
        try {
            Cipher cipher = initializedCipher(Cipher.DECRYPT_MODE, sequence);
            cipher.updateAAD(aad, aadOffset, aadLength);
            return cipher.doFinal(
                    ciphertext,
                    ciphertextOffset,
                    ciphertextLength,
                    output,
                    outputOffset
            );
        } catch (AEADBadTagException exception) {
            throw new PyVpnProtocolException("invalid encrypted tunnel packet", exception);
        } catch (GeneralSecurityException exception) {
            throw new PyVpnProtocolException("ChaCha20-Poly1305 is unavailable", exception);
        }
    }

    private Cipher initializedCipher(int mode, long sequence)
            throws GeneralSecurityException, PyVpnProtocolException {
        byte[] nonce = directionKey.nonce(sequence);
        Cipher cipher = mode == Cipher.ENCRYPT_MODE ? encryptionCipher() : decryptionCipher();
        try {
            cipher.init(mode, key, new IvParameterSpec(nonce));
            return cipher;
        } catch (GeneralSecurityException firstFailure) {
            // A few vendor providers do not support reinitializing an AEAD Cipher instance.
            // Recreate only that direction and retry with the same key, nonce, and algorithm.
            if (mode == Cipher.ENCRYPT_MODE) {
                encryptionCipher = createCipher();
                cipher = encryptionCipher;
            } else {
                decryptionCipher = createCipher();
                cipher = decryptionCipher;
            }
            cipher.init(mode, key, new IvParameterSpec(nonce));
            return cipher;
        }
    }

    private Cipher encryptionCipher() throws GeneralSecurityException {
        if (encryptionCipher == null) {
            encryptionCipher = createCipher();
        }
        return encryptionCipher;
    }

    private Cipher decryptionCipher() throws GeneralSecurityException {
        if (decryptionCipher == null) {
            decryptionCipher = createCipher();
        }
        return decryptionCipher;
    }

    private static void requireRange(byte[] value, int offset, int length, String name)
            throws PyVpnProtocolException {
        if (value == null || offset < 0 || length < 0 || offset > value.length - length) {
            throw new PyVpnProtocolException("invalid " + name + " range");
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
