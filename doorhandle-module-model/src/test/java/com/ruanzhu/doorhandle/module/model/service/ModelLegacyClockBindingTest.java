package com.ruanzhu.doorhandle.module.model.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.module.model.entity.ModelOperationLog;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.sql.ResultSet;
import java.time.LocalDateTime;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/** Pure reader binding only; no fake backup is passed to a copy or production migration. */
class ModelLegacyClockBindingTest {
    private final ObjectMapper json=new ObjectMapper();
    private String clock(int originalId)throws Exception{
        // Complete six-column source fixture bytes bind this type test's source snapshot.
        String original="{\"id\":11,\"model_id\":7,\"operation_type\":\"PUBLISH\",\"operator\":null,\"operation_time\":\"2026-10-14 16:30:00\",\"remark\":null}";
        String snapshot=HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(original.getBytes(StandardCharsets.UTF_8)));
        return json.writeValueAsString(Map.of("protocol","doorhandle-legacy-clock-v1","status","UNRESOLVED","sourceTable","model_operation_log",
                "sourceKey",Map.of("id",originalId),"sourceSnapshotSha256",snapshot,
                // Opaque exporter attestation for the parser; actual MYSQL_JSON_SHA256_V1 is exercised by native COPY tests.
                "sourceRowSha256","b".repeat(64),"sourceWallTimes",Map.of("operation_time","2026-10-14 16:30:00")));
    }
    @SuppressWarnings("unchecked")
    private ModelOperationLog read(String evidence,LocalDateTime absolute,String retainedRaw)throws Exception{
        var jdbc=mock(JdbcTemplate.class);var row=mock(ResultSet.class);
        when(row.getInt("payload_version")).thenReturn(1);when(row.getLong("id")).thenReturn(101L);when(row.getInt("detection_model_id")).thenReturn(7);
        when(row.getString("action")).thenReturn("PUBLISH");when(row.getString("legacy_source")).thenReturn("model_operation_log");when(row.getString("legacy_key")).thenReturn("11");
        when(row.getString("legacy_clock_json")).thenReturn(evidence);when(row.getObject("occurred_at",LocalDateTime.class)).thenReturn(absolute);
        when(row.getString("payload_json")).thenReturn(json.writeValueAsString(new ModelOperationAuditStore.ModelOperationV1(null,null,retainedRaw)));
        doAnswer(call->{RowMapper<ModelOperationLog> mapper=call.getArgument(1);return List.of(mapper.mapRow(row,0));})
                .when(jdbc).query(anyString(),any(RowMapper.class),eq(7));
        return new ModelOperationAuditStore(jdbc,json).selectByModelId(7).get(0);
    }
    @Test void unresolvedLegacyOperationTimeNeverBecomesAConfirmedBeijingInstant()throws Exception{
        var value=read(clock(11),null,"2026-10-14T16:30:00");
        assertThat(value.getOperationTime()).isNull();assertThat(value.getClockStatus()).isEqualTo("UNRESOLVED");
        assertThat(value.getSourceWallTimes()).containsEntry("operation_time","2026-10-14 16:30:00");assertThat(value.getLegacyId()).isEqualTo(11L);
    }
    @Test void currentConfirmedUtcUsesTheStoredInstantAndDoesNotParseRetainedRawAsAnInstant()throws Exception{
        var utc=LocalDateTime.of(2026,10,14,8,30);
        assertThat(read(null,utc,"2099-01-01T00:00:00").getOperationTime()).isEqualTo(utc.plusHours(8));
    }
    @Test void missingEvidenceCannotTurnNullTimeIntoAnImportTimeOrLegacyFallback(){
        assertThatThrownBy(()->read(null,null,"2026-10-14T16:30:00")).isInstanceOf(IllegalStateException.class);
    }
    @Test void mismatchedPrimaryKeyRawTimeAndConflictingAbsoluteTimeAreRejected(){
        assertThatThrownBy(()->read(clock(12),null,"2026-10-14T16:30:00")).isInstanceOf(IllegalStateException.class);
        assertThatThrownBy(()->read(clock(11),null,"2026-10-14T16:31:00")).isInstanceOf(IllegalStateException.class);
        assertThatThrownBy(()->read(clock(11),LocalDateTime.of(2026,10,14,8,30),"2026-10-14T16:30:00")).isInstanceOf(IllegalStateException.class);
    }
}
