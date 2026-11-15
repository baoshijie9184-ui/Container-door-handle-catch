package com.ruanzhu.doorhandle.module.device.service;

import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;

import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class DeviceMutationNullableReferenceTest {
    private final JdbcTemplate jdbc = mock(JdbcTemplate.class);
    private final BusinessUserDirectory users = mock(BusinessUserDirectory.class);
    private final AgentActor actor = new AgentActor(1, "supervisor", AgentActor.Role.SUPERVISOR);
    private final DeviceMutationParticipant participant = new DeviceMutationParticipant(jdbc, users);

    @BeforeEach void setup() {
        var identity = new BusinessUserDirectory.Identity(1, "supervisor", true);
        when(users.lockCurrent(1, "supervisor")).thenReturn(identity);
        when(users.current(1, "supervisor")).thenReturn(identity);
    }

    @Test void usageWithoutADeviceHasNoInventedDeviceLockOrRelatedSnapshot() {
        when(jdbc.queryForList(startsWith("SELECT device_id FROM device_usage WHERE id=?"), eq(Long.class), eq(41L)))
                .thenAnswer(call -> call.<String>getArgument(0).contains("device_id IS NOT NULL")
                        ? List.of() : Arrays.asList((Long) null));
        assertThatCode(() -> participant.prepare(actor, "DEVICE_USAGE", "returnDevice", "41", new Object[]{41L, "returned"}))
                .doesNotThrowAnyException();
        assertThat(participant.related(actor, "DEVICE_USAGE", "returnDevice", "41", new Object[]{41L, "returned"}, List.of(), true))
                .isEmpty();
        verify(jdbc, never()).queryForList(startsWith("SELECT id FROM device_management"), anyLong());
        verify(jdbc, never()).queryForList(contains(" FROM device_management WHERE id=? FOR UPDATE"), anyLong());
    }

    @Test void deletingAnEmployeeStillLocksRealDevicesButSkipsUnlinkedUsage() {
        when(jdbc.queryForList("SELECT id FROM device_management WHERE employee_id=? ORDER BY id", Long.class, 11L))
                .thenReturn(List.of(9L));
        assertThatCode(() -> participant.prepare(actor, "EMPLOYEE", "delete", "11", new Object[]{11L}))
                .doesNotThrowAnyException();
        var ordered = inOrder(jdbc);
        ordered.verify(jdbc).queryForList("SELECT id FROM employee WHERE id=? FOR UPDATE", 11L);
        ordered.verify(jdbc).queryForList("SELECT id FROM device_management WHERE id=? FOR UPDATE", 9L);
        verify(jdbc, never()).queryForList(contains(" FROM device_usage "), eq(Long.class), anyLong());
    }

    @Test void linkedUsageStillLocksTheReferencedDevice() {
        when(jdbc.queryForList("SELECT device_id FROM device_usage WHERE id=? AND device_id IS NOT NULL", Long.class, 41L))
                .thenReturn(List.of(9L));
        participant.prepare(actor, "DEVICE_USAGE", "deleteRecord", "41", new Object[]{41L});
        verify(jdbc).queryForList("SELECT id FROM device_management WHERE id=? FOR UPDATE", 9L);
    }

    @Test void hundredsOfUnchangedHistoricalUsagesNeverBlockParentEditsOrDeletion() {
        var history = java.util.stream.LongStream.rangeClosed(1, 300).boxed().toList();
        when(jdbc.queryForList(contains(" FROM device_usage "), eq(Long.class), anyLong())).thenReturn(history);
        for (String action : List.of("updateDevice", "deleteDevice")) {
            assertThatCode(() -> participant.prepare(actor, "DEVICE", action, "9", new Object[]{9L})).doesNotThrowAnyException();
            assertThat(participant.related(actor, "DEVICE", action, "9", new Object[]{9L}, List.of(), true)).isEmpty();
        }
        participant.prepare(actor, "EMPLOYEE", "delete", "11", new Object[]{11L});
        assertThat(participant.related(actor, "EMPLOYEE", "delete", "11", new Object[]{11L}, List.of(), true)).isEmpty();
        verify(jdbc, never()).queryForList(contains(" FROM device_usage "), eq(Long.class), anyLong());
        verify(jdbc).queryForList("SELECT id FROM device_alert WHERE device_id=? ORDER BY id", Long.class, 9L);
    }

    @Test void usageAuditReadsTheStoredSnapshotsWithoutLiveParentQueries() {
        var row = new java.util.LinkedHashMap<String, Object>();
        row.put("version", 3L); row.put("device_id", 9L); row.put("employee_id", 11L);
        row.put("device_code", "OLD-D9"); row.put("device_type", "OLD-TYPE"); row.put("model_name", "Original model");
        row.put("serial_number", "OLD-SERIAL"); row.put("employee_name", "Original employee");
        row.put("employee_number", "OLD-E11"); row.put("contact", "Original contact");
        when(jdbc.queryForList(contains(" FROM device_usage WHERE id=?"), eq(41L))).thenReturn(List.of(row));
        var snapshot = participant.capture(actor, "DEVICE_USAGE", "updateRecord", "41", true);
        assertThat(snapshot.fields()).containsEntry("device_code", "OLD-D9").containsEntry("device_type", "OLD-TYPE")
                .containsEntry("model_name", "Original model").containsEntry("serial_number", "OLD-SERIAL")
                .containsEntry("employee_name", "Original employee").containsEntry("employee_number", "OLD-E11")
                .containsEntry("contact", "Original contact");
        assertThat(snapshot.maskedFields()).containsExactly("contact");
        verify(jdbc).queryForList(contains(" FROM device_usage WHERE id=?"), eq(41L));
        verifyNoMoreInteractions(jdbc);
    }

    @Test void compoundAssignmentAuditsOnlyItsLatestReceiptAndRetainsThePreviousSnapshot() {
        when(jdbc.queryForList("SELECT id FROM device_usage WHERE device_id=? ORDER BY id DESC LIMIT 1", Long.class, 9L))
                .thenReturn(List.of(41L), List.of(42L));
        when(jdbc.queryForList(contains(" FROM device_usage WHERE id=?"), eq(41L))).thenReturn(List.of(java.util.Map.of("version", 0L)));
        when(jdbc.queryForList(contains(" FROM device_usage WHERE id=?"), eq(42L))).thenReturn(List.of(java.util.Map.of("version", 0L)));
        var before = participant.related(actor, "DEVICE", "assignDeviceToEmployee", "9", new Object[]{11L, 9L}, List.of(), true);
        var after = participant.related(actor, "DEVICE", "assignDeviceToEmployee", "9", new Object[]{11L, 9L}, before, false);
        assertThat(before).extracting(item -> item.resourceId()).containsExactly("41");
        assertThat(after).extracting(item -> item.resourceId()).containsExactly("41", "42");
        verify(jdbc, never()).queryForList("SELECT id FROM device_usage WHERE device_id=? ORDER BY id", Long.class, 9L);
    }
}
