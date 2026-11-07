package com.ruanzhu.doorhandle.framework.persistence.chat;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.time.LegacyClockEvidence;
import java.math.BigInteger;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.LocalDateTime;
import java.util.*;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/** Typed protocol binding only; real source snapshot/native MySQL hashes are tested by the copy suite. */
class JdbcMessageEvidenceClockTest {
    private final ObjectMapper json=new ObjectMapper();
    private final JdbcTemplate jdbc=mock(JdbcTemplate.class);
    private final JdbcMessageEvidenceStore reader=new JdbcMessageEvidenceStore(jdbc,json);
    private static final String ID="9223372036854775810",WALL="2026-10-17 12:34:56.123456";
    private String hash(String text)throws Exception{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(text.getBytes(StandardCharsets.UTF_8)));}
    private String clock(String table,String id)throws Exception{
        // Complete six-column synthetic source fixture, without claiming native MYSQL_JSON_SHA256_V1 attestation.
        String source=json.writeValueAsString(Map.of("id",new BigInteger(id),"user_id",1,"session_id","owned-session","message_id",11,"run_id","retained-run","created_at",WALL));
        return json.writeValueAsString(Map.of("protocol",LegacyClockEvidence.PROTOCOL,"status","UNRESOLVED","sourceTable",table,
            "sourceKey",Map.of("id",new BigInteger(id)),"sourceSnapshotSha256",hash(source),"sourceRowSha256",hash(source),"sourceWallTimes",Map.of("created_at",WALL)));
    }
    private Map<String,Object> event(boolean unknown)throws Exception{
        var event=new LinkedHashMap<String,Object>();event.put("kind",MessageEvidence.EXECUTION);event.put("owner_user_id",1L);event.put("message_id",11L);event.put("current_message",11L);
        event.put("resource_type","CHAT_MESSAGE");event.put("resource_id","11");event.put("payload_version",1);event.put("actor_user_id",null);event.put("action","RECORDED");event.put("session_id","owned-session");event.put("run_id","retained-run");
        event.put("payload_json",json.writeValueAsString(new MessageEvidence.ExecutionV1(unknown?ID:null,WALL,unknown?null:"+00:00")));
        event.put("content_sha256",hash((String)event.get("payload_json")));event.put("occurred_at",unknown?null:LocalDateTime.parse("2026-10-17T12:34:56.123456"));
        event.put("legacy_source",unknown?"agent_message_execution":null);event.put("legacy_key",unknown?ID:null);event.put("legacy_clock_json",unknown?clock("agent_message_execution",ID):null);return event;
    }
    private MessageEvidence.ExecutionLink read(Map<String,Object> event){when(jdbc.queryForList(anyString(),any(Object[].class))).thenReturn(List.of(event));return reader.executionDetails(1,"owned-session",List.of(11L)).get(11L);}
    @Test void unknownUnsignedIdentityRetainsRunAndExactWallWithoutAnAbsoluteTime()throws Exception{
        var row=event(true);var before=new LinkedHashMap<>(row);var detail=read(row);
        assertThat(detail.runId()).isEqualTo("retained-run");assertThat(detail.clockStatus()).isEqualTo("UNRESOLVED");assertThat(detail.sourceWallTimes()).containsExactly(Map.entry("created_at",WALL));
        assertThatThrownBy(()->detail.sourceWallTimes().put("created_at","changed")).isInstanceOf(UnsupportedOperationException.class);
        assertThat(row).isEqualTo(before);assertThat(reader.executionLinks(1,"owned-session",List.of(11L))).containsEntry(11L,"retained-run");
    }
    @Test void missingOffsetWithoutItsSidecarCannotBecomeKnownUtc()throws Exception{
        var row=event(true);row.put("legacy_clock_json",null);assertThatThrownBy(()->read(row)).isInstanceOf(IllegalStateException.class);
        row.remove("legacy_clock_json");assertThatThrownBy(()->read(row)).isInstanceOf(IllegalStateException.class);
    }
    @Test void anotherSourcePrimaryKeyOrInventedAbsoluteTimeCannotReuseTheProof()throws Exception{
        var wrongKey=event(true);wrongKey.put("legacy_clock_json",clock("agent_message_execution","17"));assertThatThrownBy(()->read(wrongKey)).isInstanceOf(IllegalStateException.class);
        var wrongTable=event(true);wrongTable.put("legacy_clock_json",clock("agent_workspace_turn_snapshot",ID));assertThatThrownBy(()->read(wrongTable)).isInstanceOf(IllegalStateException.class);
        var invented=event(true);invented.put("occurred_at",LocalDateTime.parse("2026-10-17T04:34:56.123456"));assertThatThrownBy(()->read(invented)).isInstanceOf(IllegalStateException.class);
    }
    @Test void changedRawWallOrPayloadBytesAreRejected()throws Exception{
        var row=event(true);row.put("payload_json",json.writeValueAsString(new MessageEvidence.ExecutionV1(ID,"2026-10-17 04:34:56.123456",null)));row.put("content_sha256",hash((String)row.get("payload_json")));
        assertThatThrownBy(()->read(row)).isInstanceOf(IllegalStateException.class);
        var tampered=event(true);tampered.put("content_sha256","0".repeat(64));assertThatThrownBy(()->read(tampered)).isInstanceOf(IllegalStateException.class);
    }
    @Test void knownNewLinksStillExposeConfirmedUtcProvenance()throws Exception{
        var detail=read(event(false));assertThat(detail.clockStatus()).isEqualTo("UTC");assertThat(detail.sourceWallTimes()).isEmpty();assertThat(detail.runId()).isEqualTo("retained-run");
    }
    @Test void unknownSnapshotCanBeReadWithoutChangingItsOriginalBody()throws Exception{
        var row=event(true);String body="{ \"files\" : [], \"business\" : [] }";
        row.put("kind",MessageEvidence.SNAPSHOT);row.put("run_id",null);row.put("legacy_source","agent_workspace_turn_snapshot");row.put("legacy_clock_json",clock("agent_workspace_turn_snapshot",ID));
        row.put("payload_json",json.writeValueAsString(new MessageEvidence.WorkspaceSnapshotV1(ID,body,WALL,null)));row.put("content_sha256",hash(body));
        when(jdbc.queryForList(anyString(),any(Object[].class))).thenReturn(List.of(row));assertThat(reader.loadSnapshot(1,"owned-session",11)).isEqualTo(body);
    }
}
