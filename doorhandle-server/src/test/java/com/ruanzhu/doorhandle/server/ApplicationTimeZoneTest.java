package com.ruanzhu.doorhandle.server;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.parallel.ResourceLock;
import java.time.*;
import java.util.TimeZone;
import static org.assertj.core.api.Assertions.assertThat;

class ApplicationTimeZoneTest {
    @Test @ResourceLock("java.util.TimeZone.default")
    void businessClockUsesUtcPlusEightEvenWhenHostStartsInUtc() {
        var original=TimeZone.getDefault();
        try {
            TimeZone.setDefault(TimeZone.getTimeZone("UTC"));
            DoorHandleCatchApplication.configureTimeZone();
            assertThat(ZoneId.systemDefault().getRules().getOffset(Instant.now())).isEqualTo(ZoneOffset.ofHours(8));
            var start=Instant.now();var local=LocalDateTime.now().toInstant(ZoneOffset.ofHours(8));var end=Instant.now();
            assertThat(local).isBetween(start,end);
        } finally { TimeZone.setDefault(original); }
    }
}
