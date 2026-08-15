package com.penghanli.pyvpn.protocol;

import java.util.BitSet;

public final class ReplayWindow {
    private final int size;
    private long maxSequence;
    private BitSet seen;

    public ReplayWindow() {
        this(1024);
    }

    public ReplayWindow(int size) {
        if (size <= 0) {
            throw new IllegalArgumentException("replay window size must be positive");
        }
        this.size = size;
        this.seen = new BitSet(size);
    }

    public synchronized boolean accept(long sequence) {
        if (sequence <= 0) {
            return false;
        }
        if (maxSequence == 0) {
            maxSequence = sequence;
            seen.set(0);
            return true;
        }
        if (sequence > maxSequence) {
            long shiftValue = sequence - maxSequence;
            BitSet shifted = new BitSet(size);
            if (shiftValue < size) {
                int shift = (int) shiftValue;
                for (int bit = seen.nextSetBit(0); bit >= 0; bit = seen.nextSetBit(bit + 1)) {
                    if (bit + shift < size) {
                        shifted.set(bit + shift);
                    }
                }
            }
            shifted.set(0);
            seen = shifted;
            maxSequence = sequence;
            return true;
        }
        long offsetValue = maxSequence - sequence;
        if (offsetValue >= size) {
            return false;
        }
        int offset = (int) offsetValue;
        if (seen.get(offset)) {
            return false;
        }
        seen.set(offset);
        return true;
    }
}
