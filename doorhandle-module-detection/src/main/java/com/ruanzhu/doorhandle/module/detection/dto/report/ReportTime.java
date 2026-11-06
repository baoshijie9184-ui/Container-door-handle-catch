package com.ruanzhu.doorhandle.module.detection.dto.report;

import java.time.LocalDateTime;
import java.time.ZoneId;
import java.time.ZoneOffset;

/** Existing report DTOs and the report main table use Beijing wall time; shared persistence uses UTC. */
public final class ReportTime {
    public static final ZoneId BEIJING = ZoneId.of("Asia/Shanghai");
    private ReportTime() { }

    public static LocalDateTime fromUtc(LocalDateTime value) {
        return value == null ? null : value.atOffset(ZoneOffset.UTC).atZoneSameInstant(BEIJING).toLocalDateTime();
    }
}
