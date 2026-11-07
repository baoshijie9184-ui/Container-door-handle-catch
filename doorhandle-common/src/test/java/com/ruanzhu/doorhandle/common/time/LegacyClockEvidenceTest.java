package com.ruanzhu.doorhandle.common.time;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.LinkedHashMap;
import java.util.Map;
import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.*;

class LegacyClockEvidenceTest {
    private final ObjectMapper json = new ObjectMapper();
    private Map<String,Object> source() {
        var times = new LinkedHashMap<String,Object>();
        times.put("created_at", "2026-10-17 11:43:52.871087");
        times.put("expires_at", null);
        return new LinkedHashMap<>(Map.of("protocol",LegacyClockEvidence.PROTOCOL,"status","UNRESOLVED",
                "sourceTable","agent_conversation_input","sourceKey",Map.of("id",7),
                "sourceSnapshotSha256","a".repeat(64),"sourceRowSha256","b".repeat(64),"sourceWallTimes",times));
    }
    private LegacyClockEvidence read(Map<String,Object> value) throws Exception {
        return LegacyClockEvidence.parse(json.writeValueAsString(value),"agent_conversation_input",Map.of("id",7L));
    }
    @Test void exactIdentityPreservesMicrosecondsAndSqlNullWithoutInventingInstants() throws Exception {
        var evidence = read(source());
        assertThat(evidence.clockStatus()).isEqualTo("UNRESOLVED");
        assertThat(evidence.sourceKey()).containsOnlyKeys("id");
        assertThat(evidence.sourceWallTimes()).containsEntry("created_at","2026-10-17 11:43:52.871087").containsEntry("expires_at",null);
        evidence.requireWallTime("created_at","2026-10-17 11:43:52.871087");
        evidence.requireWallTime("expires_at",null);
        assertThatThrownBy(()->evidence.requireWallTime("missing",null)).isInstanceOf(IllegalStateException.class);
        assertThatThrownBy(()->evidence.sourceWallTimes().put("created_at","changed")).isInstanceOf(UnsupportedOperationException.class);
        assertThatThrownBy(()->evidence.sourceKey().put("id",8)).isInstanceOf(UnsupportedOperationException.class);
    }
    @Test void optionalAllowsOnlyActualSqlNull() {
        assertThat(LegacyClockEvidence.optional(null,"agent_conversation_input",Map.of("id",7))).isEmpty();
        for(String invalid:new String[]{"", "null", "[]", "{}", "{} {}"})
            assertThatThrownBy(()->LegacyClockEvidence.optional(invalid,"agent_conversation_input",Map.of("id",7)))
                    .isInstanceOf(IllegalStateException.class);
    }
    @Test void rejectsExtraMissingAndDuplicateFieldsRatherThanIgnoringNewProtocolData() throws Exception {
        var extra=source();extra.put("offset","+08:00");assertThatThrownBy(()->read(extra)).isInstanceOf(IllegalStateException.class);
        var missing=source();missing.remove("status");assertThatThrownBy(()->read(missing)).isInstanceOf(IllegalStateException.class);
        String valid=json.writeValueAsString(source());
        String duplicate=valid.substring(0,valid.length()-1)+",\"status\":\"UNRESOLVED\"}";
        assertThatThrownBy(()->LegacyClockEvidence.parse(duplicate,"agent_conversation_input",Map.of("id",7)))
                .isInstanceOf(IllegalStateException.class);
        String repeatedKey=valid.replace("\"id\":7","\"id\":7,\"id\":7");
        assertThatThrownBy(()->LegacyClockEvidence.parse(repeatedKey,"agent_conversation_input",Map.of("id",7)))
                .isInstanceOf(IllegalStateException.class);
    }
    @Test void tablePrimaryKeyTypeAndExactKeySetCannotBorrowAnotherRowsException() throws Exception {
        String valid=json.writeValueAsString(source());
        assertThatThrownBy(()->LegacyClockEvidence.parse(valid,"agent_run",Map.of("id",7))).isInstanceOf(IllegalStateException.class);
        assertThatThrownBy(()->LegacyClockEvidence.parse(valid,"agent_conversation_input",Map.of("id",8))).isInstanceOf(IllegalStateException.class);
        assertThatThrownBy(()->LegacyClockEvidence.parse(valid,"agent_conversation_input",Map.of("id","7"))).isInstanceOf(IllegalStateException.class);
        var extra=source();extra.put("sourceKey",Map.of("id",7,"owner_user_id",1));
        assertThatThrownBy(()->read(extra)).isInstanceOf(IllegalStateException.class);
    }
    @Test void malformedHashStatusAndOffsetOrInvalidWallDatesAreRejectedWithoutEchoingPayload() throws Exception {
        for(String field:new String[]{"sourceRowSha256","sourceSnapshotSha256","protocol","status"}){
            var bad=source();bad.put(field,"PRIVATE-INVALID-PAYLOAD");
            assertThatThrownBy(()->read(bad)).isInstanceOf(IllegalStateException.class).hasMessageNotContaining("PRIVATE-INVALID");
        }
        for(String time:new String[]{"2026-10-17T11:43:52Z","2026-10-17 11:43:52+08:00","2026-02-31 11:43:52",
                "2026-10-17 11:43:52.1234567","2026-10-17 11:43:52 ","1970-01-01"}){
            var bad=source();bad.put("sourceWallTimes",Map.of("created_at",time));
            assertThatThrownBy(()->read(bad)).isInstanceOf(IllegalStateException.class);
        }
    }
    @Test void dateLessLegacyReceiptsCanRetainAnEmptyWallClockObject() throws Exception {
        var value=source();value.put("sourceWallTimes",Map.of());
        assertThat(read(value).sourceWallTimes()).isEmpty();
    }
}
