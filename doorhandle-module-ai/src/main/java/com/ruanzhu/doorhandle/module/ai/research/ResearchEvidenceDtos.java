package com.ruanzhu.doorhandle.module.ai.research;

import java.time.LocalDateTime;
import java.util.List;

/** 私有调研视图；摘录是未受信任的纯文本，引用表示标记匹配而非结论核实。 */
public final class ResearchEvidenceDtos {
    private ResearchEvidenceDtos() {}
    public record Source(String sourceId, String runId, String callId, String requestedUrl, boolean queryOmitted, boolean urlRedacted,
                         String title, String excerpt, String contentSha256, int textChars, int startIndex, int maxLength,
                         LocalDateTime fetchedAt, LocalDateTime expiresAt) {}
    /** UTF-16 偏移，与 Java String / JavaScript 字符串一致，end 不包含右端点。 */
    public record Citation(String sourceId, int start, int end) {}
    public record View(String runId, boolean enabled, List<Source> sources, List<Citation> citations,
                       String answerSha256, boolean answerRecorded, int unresolvedCitationCount, int expiredSourceCount, boolean exportEnabled) {
        public View(String runId, boolean enabled, List<Source> sources, List<Citation> citations,
                    String answerSha256, boolean answerRecorded, int unresolvedCitationCount, int expiredSourceCount) {
            this(runId,enabled,sources,citations,answerSha256,answerRecorded,unresolvedCitationCount,expiredSourceCount,false);
        }
        public View withExportEnabled(boolean value) { return new View(runId,enabled,sources,citations,answerSha256,answerRecorded,unresolvedCitationCount,expiredSourceCount,enabled&&value); }
        public static View disabled(String runId) { return new View(runId, false, List.of(), List.of(), null, false, 0, 0); }
    }
}
