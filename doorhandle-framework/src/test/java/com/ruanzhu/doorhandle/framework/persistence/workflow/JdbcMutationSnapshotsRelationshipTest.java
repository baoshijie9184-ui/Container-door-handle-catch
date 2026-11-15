package com.ruanzhu.doorhandle.framework.persistence.workflow;

import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class JdbcMutationSnapshotsRelationshipTest {
    @Test void originalMappingConstructorStillResolvesCurrentRelationshipLabels() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        var mapping = new JdbcMutationSnapshots.Mapping("DEVICE", "device_management", "id", "version",
                List.of("employee_id", "device_id", "department_id"), Set.of(), Set.of());
        when(jdbc.queryForList(contains(" FROM device_management WHERE id=?"), eq(9L)))
                .thenReturn(List.of(Map.of("employee_id", 11L, "device_id", 9L, "department_id", 2L, "version", 3L)));
        when(jdbc.queryForList("SELECT name,employee_number FROM employee WHERE id=?", 11L))
                .thenReturn(List.of(Map.of("name", "Current employee", "employee_number", "E11")));
        when(jdbc.queryForList("SELECT name FROM organization_department WHERE id=?", 2L))
                .thenReturn(List.of(Map.of("name", "Current department")));
        when(jdbc.queryForList("SELECT device_code,model_name FROM device_management WHERE id=?", 9L))
                .thenReturn(List.of(Map.of("device_code", "D9", "model_name", "Current model")));
        var snapshot = new JdbcMutationSnapshots(jdbc).capture(mapping, "9", true);
        assertThat(mapping.resolveRelationships()).isTrue();
        assertThat(snapshot.fields()).containsEntry("employee_name", "Current employee")
                .containsEntry("employee_number", "E11").containsEntry("department_name", "Current department")
                .containsEntry("device_code", "D9").containsEntry("device_model_name", "Current model");
    }

    @Test void retainedSnapshotsNeverResolveMissingOrChangedParentsAndKeepNulls() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        var fields = List.of("employee_id", "device_id", "employee_name", "employee_number", "device_code", "contact");
        var mapping = new JdbcMutationSnapshots.Mapping("DEVICE_USAGE", "device_usage", "id", "version",
                fields, Set.of("contact"), Set.of(), false);
        var row = new LinkedHashMap<String, Object>();
        row.put("employee_id", 11L); row.put("device_id", 9L); row.put("version", 3L);
        row.put("employee_name", "Original employee"); row.put("employee_number", "E-OLD");
        row.put("device_code", "D-OLD"); row.put("contact", null);
        when(jdbc.queryForList(contains(" FROM device_usage WHERE id=?"), eq(41L))).thenReturn(List.of(row));
        var snapshots = new JdbcMutationSnapshots(jdbc);
        var before = snapshots.capture(mapping, "41", true);
        var after = snapshots.capture(mapping, "41", false);
        assertThat(after.fields()).isEqualTo(before.fields()).containsEntry("employee_id", "11")
                .containsEntry("device_id", "9").containsEntry("employee_name", "Original employee")
                .containsEntry("employee_number", "E-OLD").containsEntry("device_code", "D-OLD").containsEntry("contact", null);
        assertThat(after.maskedFields()).containsExactly("contact");
        verify(jdbc, times(2)).queryForList(contains(" FROM device_usage WHERE id=?"), eq(41L));
        verifyNoMoreInteractions(jdbc);
    }
}
