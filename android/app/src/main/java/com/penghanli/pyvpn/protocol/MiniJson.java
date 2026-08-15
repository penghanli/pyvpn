package com.penghanli.pyvpn.protocol;

import java.math.BigDecimal;
import java.math.BigInteger;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public final class MiniJson {
    private MiniJson() {}

    public static Object parse(String value) throws PyVpnProtocolException {
        Parser parser = new Parser(value);
        Object parsed = parser.parseValue();
        parser.skipWhitespace();
        if (!parser.atEnd()) {
            throw parser.error("unexpected trailing JSON content");
        }
        return parsed;
    }

    @SuppressWarnings("unchecked")
    public static Map<String, Object> parseObject(String value) throws PyVpnProtocolException {
        Object parsed = parse(value);
        if (!(parsed instanceof Map<?, ?>)) {
            throw new PyVpnProtocolException("control frame must be a JSON object");
        }
        return (Map<String, Object>) parsed;
    }

    public static String stringify(Object value) {
        StringBuilder output = new StringBuilder();
        writeValue(output, value);
        return output.toString();
    }

    private static void writeValue(StringBuilder output, Object value) {
        if (value == null) {
            output.append("null");
        } else if (value instanceof String text) {
            writeString(output, text);
        } else if (value instanceof Boolean || value instanceof Number) {
            output.append(value);
        } else if (value instanceof Map<?, ?> map) {
            output.append('{');
            boolean first = true;
            for (Map.Entry<?, ?> entry : map.entrySet()) {
                if (!(entry.getKey() instanceof String key)) {
                    throw new IllegalArgumentException("JSON object keys must be strings");
                }
                if (!first) {
                    output.append(',');
                }
                first = false;
                writeString(output, key);
                output.append(':');
                writeValue(output, entry.getValue());
            }
            output.append('}');
        } else if (value instanceof Iterable<?> iterable) {
            output.append('[');
            boolean first = true;
            for (Object item : iterable) {
                if (!first) {
                    output.append(',');
                }
                first = false;
                writeValue(output, item);
            }
            output.append(']');
        } else {
            throw new IllegalArgumentException("unsupported JSON value: " + value.getClass());
        }
    }

    private static void writeString(StringBuilder output, String value) {
        output.append('"');
        for (int index = 0; index < value.length(); index++) {
            char character = value.charAt(index);
            switch (character) {
                case '"' -> output.append("\\\"");
                case '\\' -> output.append("\\\\");
                case '\b' -> output.append("\\b");
                case '\f' -> output.append("\\f");
                case '\n' -> output.append("\\n");
                case '\r' -> output.append("\\r");
                case '\t' -> output.append("\\t");
                default -> {
                    if (character < 0x20) {
                        output.append(String.format("\\u%04x", (int) character));
                    } else {
                        output.append(character);
                    }
                }
            }
        }
        output.append('"');
    }

    private static final class Parser {
        private final String input;
        private int position;

        private Parser(String input) {
            this.input = input;
        }

        private boolean atEnd() {
            return position >= input.length();
        }

        private void skipWhitespace() {
            while (!atEnd()) {
                char value = input.charAt(position);
                if (value != ' ' && value != '\n' && value != '\r' && value != '\t') {
                    return;
                }
                position++;
            }
        }

        private Object parseValue() throws PyVpnProtocolException {
            skipWhitespace();
            if (atEnd()) {
                throw error("unexpected end of JSON");
            }
            return switch (input.charAt(position)) {
                case '{' -> parseObject();
                case '[' -> parseArray();
                case '"' -> parseString();
                case 't' -> parseLiteral("true", Boolean.TRUE);
                case 'f' -> parseLiteral("false", Boolean.FALSE);
                case 'n' -> parseLiteral("null", null);
                default -> parseNumber();
            };
        }

        private Map<String, Object> parseObject() throws PyVpnProtocolException {
            position++;
            LinkedHashMap<String, Object> result = new LinkedHashMap<>();
            skipWhitespace();
            if (consume('}')) {
                return result;
            }
            while (true) {
                skipWhitespace();
                if (atEnd() || input.charAt(position) != '"') {
                    throw error("JSON object key must be a string");
                }
                String key = parseString();
                skipWhitespace();
                require(':');
                result.put(key, parseValue());
                skipWhitespace();
                if (consume('}')) {
                    return result;
                }
                require(',');
            }
        }

        private List<Object> parseArray() throws PyVpnProtocolException {
            position++;
            ArrayList<Object> result = new ArrayList<>();
            skipWhitespace();
            if (consume(']')) {
                return result;
            }
            while (true) {
                result.add(parseValue());
                skipWhitespace();
                if (consume(']')) {
                    return result;
                }
                require(',');
            }
        }

        private String parseString() throws PyVpnProtocolException {
            require('"');
            StringBuilder result = new StringBuilder();
            while (!atEnd()) {
                char value = input.charAt(position++);
                if (value == '"') {
                    return result.toString();
                }
                if (value < 0x20) {
                    throw error("unescaped control character in JSON string");
                }
                if (value != '\\') {
                    result.append(value);
                    continue;
                }
                if (atEnd()) {
                    throw error("truncated JSON escape");
                }
                char escaped = input.charAt(position++);
                switch (escaped) {
                    case '"', '\\', '/' -> result.append(escaped);
                    case 'b' -> result.append('\b');
                    case 'f' -> result.append('\f');
                    case 'n' -> result.append('\n');
                    case 'r' -> result.append('\r');
                    case 't' -> result.append('\t');
                    case 'u' -> result.append(parseUnicodeEscape());
                    default -> throw error("invalid JSON escape");
                }
            }
            throw error("unterminated JSON string");
        }

        private char parseUnicodeEscape() throws PyVpnProtocolException {
            if (position + 4 > input.length()) {
                throw error("truncated Unicode escape");
            }
            String digits = input.substring(position, position + 4);
            position += 4;
            try {
                return (char) Integer.parseInt(digits, 16);
            } catch (NumberFormatException exception) {
                throw error("invalid Unicode escape");
            }
        }

        private Object parseLiteral(String literal, Object value) throws PyVpnProtocolException {
            if (!input.startsWith(literal, position)) {
                throw error("invalid JSON value");
            }
            position += literal.length();
            return value;
        }

        private Number parseNumber() throws PyVpnProtocolException {
            int start = position;
            consume('-');
            if (consume('0')) {
                if (!atEnd() && Character.isDigit(input.charAt(position))) {
                    throw error("invalid leading zero in JSON number");
                }
            } else {
                requireDigits();
            }
            boolean decimal = false;
            if (consume('.')) {
                decimal = true;
                requireDigits();
            }
            if (!atEnd() && (input.charAt(position) == 'e' || input.charAt(position) == 'E')) {
                decimal = true;
                position++;
                if (!atEnd() && (input.charAt(position) == '+' || input.charAt(position) == '-')) {
                    position++;
                }
                requireDigits();
            }
            String number = input.substring(start, position);
            try {
                return decimal ? new BigDecimal(number) : new BigInteger(number);
            } catch (NumberFormatException exception) {
                throw error("invalid JSON number");
            }
        }

        private void requireDigits() throws PyVpnProtocolException {
            int start = position;
            while (!atEnd() && Character.isDigit(input.charAt(position))) {
                position++;
            }
            if (start == position) {
                throw error("JSON number requires a digit");
            }
        }

        private boolean consume(char expected) {
            if (!atEnd() && input.charAt(position) == expected) {
                position++;
                return true;
            }
            return false;
        }

        private void require(char expected) throws PyVpnProtocolException {
            if (!consume(expected)) {
                throw error("expected '" + expected + "'");
            }
        }

        private PyVpnProtocolException error(String message) {
            return new PyVpnProtocolException(message + " at character " + position);
        }
    }
}
