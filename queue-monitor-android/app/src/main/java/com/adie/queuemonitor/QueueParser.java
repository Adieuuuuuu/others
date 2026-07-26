package com.adie.queuemonitor;

import java.util.regex.Matcher;
import java.util.regex.Pattern;

final class QueueParser {
    private QueueParser() {}

    private static final Pattern[] TABLE_PATTERNS = new Pattern[] {
            Pattern.compile("(?:前方|前面|前边)(?:还有|尚有|等待|排队|共)?\\s*[：:]?\\s*(\\d{1,4})\\s*(?:桌|组)"),
            Pattern.compile("(?:还需|尚需|需要|预计)?\\s*(?:等待|排队)\\s*[：:]?\\s*(\\d{1,4})\\s*(?:桌|组)"),
            Pattern.compile("(\\d{1,4})\\s*(?:桌|组)\\s*(?:在前方|等待中|排队中)"),
            Pattern.compile("(?:前方|前面)[^\\n\\r]{0,24}?(\\d{1,4})\\s*(?:桌|组)")
    };

    static Result detect(String rawText) {
        String text = normalize(rawText);
        for (Pattern pattern : TABLE_PATTERNS) {
            Matcher matcher = pattern.matcher(text);
            if (matcher.find()) {
                try {
                    int tables = Integer.parseInt(matcher.group(1));
                    if (tables >= 0 && tables <= 9999) {
                        return new Result(tables, matcher.group(0).trim());
                    }
                } catch (NumberFormatException ignored) {
                    // Try the next pattern.
                }
            }
        }
        return null;
    }

    static boolean looksLikeLogin(String url, String rawText) {
        String lowerUrl = url == null ? "" : url.toLowerCase();
        String text = normalize(rawText);
        return lowerUrl.contains("mlogin")
                || lowerUrl.contains("smslogin")
                || text.contains("短信登录")
                || text.contains("验证码登录")
                || text.contains("获取验证码")
                || text.contains("登录后查看");
    }

    private static String normalize(String input) {
        if (input == null) return "";
        return input
                .replace('\u00A0', ' ')
                .replaceAll("[ \\t]+", " ")
                .replaceAll("\\n{3,}", "\\n\\n")
                .trim();
    }

    static final class Result {
        final int tables;
        final String matchedText;

        Result(int tables, String matchedText) {
            this.tables = tables;
            this.matchedText = matchedText;
        }
    }
}
