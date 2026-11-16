package com.ruanzhu.doorhandle.module.device.service.impl;

import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.module.device.entity.Device;
import com.ruanzhu.doorhandle.module.device.entity.DeviceUsageRecord;
import com.ruanzhu.doorhandle.module.device.entity.Employee;
import com.ruanzhu.doorhandle.module.device.mapper.DeviceMapper;
import com.ruanzhu.doorhandle.module.device.mapper.DeviceUsageRecordMapper;
import com.ruanzhu.doorhandle.module.device.mapper.EmployeeMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class DeviceUsageHistoryServiceTest {
    private final DeviceMapper devices = mock(DeviceMapper.class);
    private final EmployeeMapper employees = mock(EmployeeMapper.class);
    private final DeviceUsageRecordMapper records = mock(DeviceUsageRecordMapper.class);
    private final DeviceUsageRecordServiceImpl service = spy(new DeviceUsageRecordServiceImpl());

    @BeforeEach void setup() {
        ReflectionTestUtils.setField(service, "deviceMapper", devices);
        ReflectionTestUtils.setField(service, "employeeMapper", employees);
        ReflectionTestUtils.setField(service, "deviceUsageRecordMapper", records);
        doReturn(true).when(service).save(any(DeviceUsageRecord.class));
        doReturn(true).when(service).updateById(any(DeviceUsageRecord.class));
    }

    @Test void bothCreateEntrypointsRejectNonexistentEmployeeReferencesBeforeWriting() {
        assertThatThrownBy(() -> service.createDeviceUsageRecord(history())).isInstanceOf(BusinessException.class);
        assertThatThrownBy(() -> service.createRecord(history())).isInstanceOf(BusinessException.class);
        verifyNoInteractions(records, devices);
        verify(service, never()).save(any(DeviceUsageRecord.class));
    }

    @Test void bothCreateEntrypointsRejectNonexistentDeviceReferencesBeforeWriting() {
        when(employees.selectForUsageReference(11L)).thenReturn(new Employee());
        assertThatThrownBy(() -> service.createDeviceUsageRecord(history())).isInstanceOf(BusinessException.class);
        assertThatThrownBy(() -> service.createRecord(history())).isInstanceOf(BusinessException.class);
        verifyNoInteractions(records);
        verify(service, never()).save(any(DeviceUsageRecord.class));
    }

    @Test void newReferencesLockParentsInEmployeeDeviceOrderBeforeInsert() {
        when(employees.selectForUsageReference(11L)).thenReturn(new Employee());
        when(devices.selectForUsageReference(9L)).thenReturn(new Device());
        DeviceUsageRecord value = history();
        service.createDeviceUsageRecord(value);
        var order = inOrder(employees, devices, records);
        order.verify(employees).selectForUsageReference(11L);
        order.verify(devices).selectForUsageReference(9L);
        order.verify(records).insert(value);
        assertThat(value.getEmployeeName()).isEqualTo("Original employee");
        assertThat(value.getDeviceCode()).isEqualTo("D-OLD");
    }

    @Test void newUnlinkedRecordsRetainTheNullableReferenceContract() {
        DeviceUsageRecord value = new DeviceUsageRecord();
        assertThat(service.createRecord(value)).isTrue();
        service.createDeviceUsageRecord(value);
        verifyNoInteractions(devices, employees);
    }

    @Test void bothUpdateEntrypointsPreserveUnchangedOrphanIdsAndSnapshots() {
        DeviceUsageRecord original = history();
        when(records.selectForReferenceUpdate(41L)).thenReturn(original);
        DeviceUsageRecord update = history(); update.setRemarks("Corrected note");
        service.updateDeviceUsageRecord(update);
        assertThat(service.updateRecord(update)).isTrue();
        assertThat(update.getEmployeeId()).isEqualTo(11L); assertThat(update.getDeviceId()).isEqualTo(9L);
        assertThat(update.getEmployeeName()).isEqualTo("Original employee"); assertThat(update.getDeviceCode()).isEqualTo("D-OLD");
        verify(records).updateById(update);
        verifyNoInteractions(devices, employees);
    }

    @Test void partialUpdatesDoNotInventOrRevalidateMissingReferences() {
        when(records.selectForReferenceUpdate(41L)).thenReturn(history());
        DeviceUsageRecord update = new DeviceUsageRecord(); update.setId(41L); update.setRemarks("Corrected note");
        service.updateDeviceUsageRecord(update);
        assertThat(service.updateRecord(update)).isTrue();
        verifyNoInteractions(devices, employees);
    }

    @Test void bothUpdateEntrypointsRejectAChangedMissingParent() {
        when(records.selectForReferenceUpdate(41L)).thenReturn(history());
        DeviceUsageRecord employeeChange = history(); employeeChange.setEmployeeId(12L);
        DeviceUsageRecord deviceChange = history(); deviceChange.setDeviceId(10L);
        for (DeviceUsageRecord update : List.of(employeeChange, deviceChange)) {
            assertThatThrownBy(() -> service.updateDeviceUsageRecord(update)).isInstanceOf(BusinessException.class);
            assertThatThrownBy(() -> service.updateRecord(update)).isInstanceOf(BusinessException.class);
        }
        verify(records, never()).updateById(any(DeviceUsageRecord.class));
        verify(service, never()).updateById(any(DeviceUsageRecord.class));
    }

    @Test void changedReferencesCanPointToExistingParents() {
        when(records.selectForReferenceUpdate(41L)).thenReturn(history());
        when(employees.selectForUsageReference(12L)).thenReturn(new Employee());
        when(devices.selectForUsageReference(10L)).thenReturn(new Device());
        DeviceUsageRecord update = history(); update.setEmployeeId(12L); update.setDeviceId(10L);
        assertThat(service.updateRecord(update)).isTrue();
        var order = inOrder(employees, devices, service);
        order.verify(employees).selectForUsageReference(12L);
        order.verify(devices).selectForUsageReference(10L);
        order.verify(service).updateById(update);
    }

    @Test void historicalReturnWithoutParentsStillCompletesTheUsageRow() {
        DeviceUsageRecord original = history(); original.setStatus("IN_USE");
        when(records.selectForReferenceUpdate(41L)).thenReturn(original);
        assertThat(service.returnDevice(41L, "Completed later")).isTrue();
        assertThat(original.getStatus()).isEqualTo("RETURNED"); assertThat(original.getEndTime()).isNotNull();
        assertThat(original.getEmployeeId()).isEqualTo(11L); assertThat(original.getDeviceId()).isEqualTo(9L);
        verify(devices, never()).updateById(any(Device.class));
        verify(devices, never()).updateEmployeeId(anyLong(), any());
    }

    @Test void returningOldHistoryNeverClearsAnotherEmployeesCurrentAssignment() {
        Device current = new Device(); current.setId(9L); current.setEmployeeId(12L); current.setStatus("IN_USE");
        when(devices.selectForUsageUpdate(9L)).thenReturn(current);
        DeviceUsageRecord first = history(); first.setStatus("IN_USE");
        when(records.selectForReferenceUpdate(41L)).thenReturn(first);
        assertThat(service.returnDevice(41L, "Historical return")).isTrue();
        DeviceUsageRecord second = history(); second.setStatus("IN_USE");
        when(records.selectForReferenceUpdate(41L)).thenReturn(second);
        DeviceUsageRecord update = history(); update.setStatus("RETURNED");
        service.updateDeviceUsageRecord(update);
        assertThat(current.getEmployeeId()).isEqualTo(12L); assertThat(current.getStatus()).isEqualTo("IN_USE");
        verify(devices, never()).updateById(any(Device.class));
        verify(devices, never()).updateEmployeeId(anyLong(), any());
    }

    @Test void repeatedReturnKeepsTheOriginalCompletionTimeAndNeverTouchesANewAssignment() {
        DeviceUsageRecord original = history(); original.setEndTime(java.time.LocalDateTime.of(2020, 1, 2, 3, 4));
        when(records.selectForReferenceUpdate(41L)).thenReturn(original);
        assertThat(service.returnDevice(41L, "Repeated request")).isTrue();
        assertThat(original.getEndTime()).isEqualTo(java.time.LocalDateTime.of(2020, 1, 2, 3, 4));
        verify(service, never()).updateById(any(DeviceUsageRecord.class));
        verifyNoInteractions(devices, employees);
    }

    @Test void staleOpenHistoryCannotReleaseTheSameEmployeesNewerAssignmentByAnyMutation() {
        Device current = new Device(); current.setId(9L); current.setEmployeeId(11L); current.setStatus("IN_USE");
        when(devices.selectForUsageUpdate(9L)).thenReturn(current);
        DeviceUsageRecord newest = history(); newest.setId(42L); newest.setStatus("IN_USE");
        when(records.selectNewestForDeviceUpdate(9L)).thenReturn(newest);
        DeviceUsageRecord returning = history(); returning.setStatus("IN_USE");
        when(records.selectForReferenceUpdate(41L)).thenReturn(returning);
        assertThat(service.returnDevice(41L, "Historical return")).isTrue();
        DeviceUsageRecord deleting = history(); deleting.setStatus("IN_USE");
        when(records.selectForReferenceUpdate(41L)).thenReturn(deleting);
        service.deleteDeviceUsageRecord(41L);
        DeviceUsageRecord editing = history(); editing.setStatus("IN_USE");
        when(records.selectForReferenceUpdate(41L)).thenReturn(editing);
        DeviceUsageRecord update = history(); update.setStatus("RETURNED");
        service.updateDeviceUsageRecord(update);
        assertThat(current.getEmployeeId()).isEqualTo(11L); assertThat(current.getStatus()).isEqualTo("IN_USE");
        verify(devices, never()).updateEmployeeId(anyLong(), any());
        verify(devices, never()).updateById(any(Device.class));
        verify(records).deleteById(41L); verify(records).updateById(update);
    }

    @Test void currentOpenReceiptStillReturnsAndExplicitlyClearsItsDeviceAssignment() {
        Device current = new Device(); current.setId(9L); current.setEmployeeId(11L); current.setStatus("IN_USE");
        DeviceUsageRecord record = history(); record.setStatus("IN_USE");
        when(records.selectForReferenceUpdate(41L)).thenReturn(record);
        when(devices.selectForUsageUpdate(9L)).thenReturn(current);
        when(records.selectNewestForDeviceUpdate(9L)).thenReturn(record);
        when(devices.updateEmployeeId(9L, null)).thenReturn(1);
        assertThat(service.returnDevice(41L, "Current return")).isTrue();
        assertThat(record.getStatus()).isEqualTo("RETURNED"); assertThat(record.getEndTime()).isNotNull();
        verify(devices).updateEmployeeId(9L, null);
    }

    @Test void assignmentCreatesSnapshotsOnlyAfterLockingBothLiveParents() {
        Employee employee = new Employee(); employee.setName("Current employee"); employee.setEmployeeNumber("E11");
        Device device = new Device(); device.setDeviceCode("D9");
        when(employees.selectForUsageReference(11L)).thenReturn(employee);
        when(devices.selectForUsageReference(9L)).thenReturn(device);
        when(devices.updateById(device)).thenReturn(1);
        assertThat(service.createRecordOnAssign(9L, 11L, "Assigned")).isTrue();
        var captured = org.mockito.ArgumentCaptor.forClass(DeviceUsageRecord.class);
        verify(service).save(captured.capture());
        assertThat(captured.getValue().getEmployeeName()).isEqualTo("Current employee");
        assertThat(captured.getValue().getDeviceCode()).isEqualTo("D9");
        verify(employees, never()).selectById(anyLong());
    }

    @Test void unassignNeverFallsBackFromANewerClosedReceiptToAnOlderOpenRow() {
        Device current = new Device(); current.setId(9L); current.setEmployeeId(11L);
        when(devices.selectForUsageUpdate(9L)).thenReturn(current);
        DeviceUsageRecord newest = history(); newest.setId(42L); newest.setStatus("RETURNED");
        newest.setEndTime(java.time.LocalDateTime.of(2021, 1, 2, 0, 0));
        when(records.selectNewestForDeviceUpdate(9L)).thenReturn(newest);
        assertThat(service.updateRecordOnUnassign(9L, "Unassign")).isFalse();
        verify(service, never()).updateById(any(DeviceUsageRecord.class));
        verify(devices, never()).updateEmployeeId(anyLong(), any());
        verify(records).selectNewestForDeviceUpdate(9L);
    }

    @Test void unassignUpdatesTheSameNewestReceiptSelectedByCompoundAudit() {
        Device current = new Device(); current.setId(9L); current.setEmployeeId(11L);
        when(devices.selectForUsageUpdate(9L)).thenReturn(current);
        DeviceUsageRecord newest = history(); newest.setId(42L); newest.setStatus("IN_USE");
        when(records.selectNewestForDeviceUpdate(9L)).thenReturn(newest);
        when(devices.updateEmployeeId(9L, null)).thenReturn(1);
        assertThat(service.updateRecordOnUnassign(9L, "Unassign")).isTrue();
        assertThat(newest.getStatus()).isEqualTo("RETURNED"); assertThat(newest.getEndTime()).isNotNull();
        verify(service).updateById(newest); verify(devices).updateEmployeeId(9L, null);
    }

    @Test void employeeUnassignOffersTheLiveAssignmentToItsReceiptBeforeClearingIt() {
        var master = new EmployeeServiceImpl();
        var history = mock(com.ruanzhu.doorhandle.module.device.service.DeviceUsageRecordService.class);
        ReflectionTestUtils.setField(master, "deviceMapper", devices);
        ReflectionTestUtils.setField(master, "deviceUsageRecordService", history);
        Device current = new Device(); current.setId(9L); current.setEmployeeId(11L);
        when(devices.selectForUsageUpdate(9L)).thenReturn(current);
        when(history.updateRecordOnUnassign(9L, "设备已归还")).thenAnswer(call -> {
            assertThat(current.getEmployeeId()).isEqualTo(11L); return false;
        });
        when(devices.updateEmployeeId(9L, null)).thenReturn(1);
        assertThat(master.unassignDevice(9L)).isTrue();
        var order = inOrder(history, devices);
        order.verify(history).updateRecordOnUnassign(9L, "设备已归还");
        order.verify(devices).updateEmployeeId(9L, null);
        verify(devices, never()).updateById(any(Device.class));
    }

    @Test void historyListAndDetailReadOnlyStoredRecordsWithoutParentLookups() {
        DeviceUsageRecord value = history();
        when(records.selectById(41L)).thenReturn(value);
        when(records.findByDeviceId(9L)).thenReturn(List.of(value));
        when(records.selectRecordsByConditions(anyMap())).thenReturn(List.of(value));
        when(records.countRecordsByConditions(anyMap())).thenReturn(1);
        assertThat(service.getById(41L)).isSameAs(value);
        assertThat(service.getDeviceUsageRecordsByDeviceId(9L)).containsExactly(value);
        assertThat(service.getDeviceUsageRecords(1, 10, 9L, null, null, null, null, null, null).get("records"))
                .isEqualTo(List.of(value));
        verifyNoInteractions(devices, employees);
    }

    @Test void deletingDeviceMasterDataDoesNotExplicitlyDeleteItsUsageHistory() {
        when(devices.selectById(9L)).thenReturn(new Device()); when(devices.deleteById(9L)).thenReturn(1);
        var master = new DeviceServiceImpl(devices, mock(com.ruanzhu.doorhandle.module.device.mapper.DeviceCaptureAlertMapper.class), service);
        assertThat(master.deleteDevice(9L)).isTrue();
        verifyNoInteractions(records, employees);
    }

    @Test void deletingEmployeeMasterDataOnlyReleasesLiveDevicesNotUsageHistory() {
        var master = spy(new EmployeeServiceImpl());
        var history = mock(com.ruanzhu.doorhandle.module.device.service.DeviceUsageRecordService.class);
        var organization = mock(com.ruanzhu.doorhandle.contracts.organization.OrganizationDirectoryApi.class);
        ReflectionTestUtils.setField(master, "employeeMapper", employees);
        ReflectionTestUtils.setField(master, "deviceMapper", devices);
        ReflectionTestUtils.setField(master, "deviceUsageRecordService", history);
        ReflectionTestUtils.setField(master, "organization", organization);
        doReturn(true).when(master).removeById(11L);
        assertThat(master.delete(11L)).isTrue();
        verify(organization).assertEmployeeUnbound(11L); verify(devices).removeEmployeeFromDevices(11L);
        verifyNoInteractions(history, records);
    }

    @Test void deviceUnassignExplicitlyClearsLegacyAssignmentWithoutAnOpenReceipt() {
        Device current = new Device(); current.setId(9L); current.setEmployeeId(11L);
        when(devices.selectForUsageUpdate(9L)).thenReturn(current);
        when(devices.updateEmployeeId(9L, null)).thenReturn(1);
        var master = new DeviceServiceImpl(devices, mock(com.ruanzhu.doorhandle.module.device.mapper.DeviceCaptureAlertMapper.class), service);
        assertThat(master.removeEmployeeFromDevice(9L)).isTrue();
        verify(devices).updateEmployeeId(9L, null);
        verify(devices, never()).updateById(any(Device.class));
        verify(service, never()).updateById(any(DeviceUsageRecord.class));
    }

    @Test void deviceUnassignClosesCurrentReceiptAndDoesNotClearTwice() {
        Device current = new Device(); current.setId(9L); current.setEmployeeId(11L);
        when(devices.selectForUsageUpdate(9L)).thenReturn(current);
        DeviceUsageRecord receipt = history(); receipt.setStatus("IN_USE");
        when(records.selectNewestForDeviceUpdate(9L)).thenReturn(receipt);
        when(devices.updateEmployeeId(9L, null)).thenReturn(1);
        var master = new DeviceServiceImpl(devices, mock(com.ruanzhu.doorhandle.module.device.mapper.DeviceCaptureAlertMapper.class), service);
        assertThat(master.removeEmployeeFromDevice(9L)).isTrue();
        assertThat(receipt.getStatus()).isEqualTo("RETURNED");
        verify(service).updateById(receipt);
        verify(devices, times(1)).updateEmployeeId(9L, null);
    }

    @Test void alreadyUnassignedDeviceDoesNotTouchHistoryOrWriteAgain() {
        Device current = new Device(); current.setId(9L);
        when(devices.selectForUsageUpdate(9L)).thenReturn(current);
        var master = new DeviceServiceImpl(devices, mock(com.ruanzhu.doorhandle.module.device.mapper.DeviceCaptureAlertMapper.class), service);
        assertThat(master.removeEmployeeFromDevice(9L)).isTrue();
        verifyNoInteractions(records);
        verify(devices, never()).updateEmployeeId(anyLong(), any());
    }

    @Test void failedCurrentReceiptWriteDoesNotFallBackToClearingDevice() {
        Device current = new Device(); current.setId(9L); current.setEmployeeId(11L);
        when(devices.selectForUsageUpdate(9L)).thenReturn(current);
        DeviceUsageRecord receipt = history(); receipt.setStatus("IN_USE");
        when(records.selectNewestForDeviceUpdate(9L)).thenReturn(receipt);
        doReturn(false).when(service).updateById(receipt);
        var master = new DeviceServiceImpl(devices, mock(com.ruanzhu.doorhandle.module.device.mapper.DeviceCaptureAlertMapper.class), service);
        assertThatThrownBy(() -> master.removeEmployeeFromDevice(9L)).isInstanceOf(BusinessException.class);
        verify(devices, never()).updateEmployeeId(anyLong(), any());
    }

    @Test void failedExplicitUnassignRaisesConflictInsteadOfReportingSuccess() {
        Device current = new Device(); current.setId(9L); current.setEmployeeId(11L);
        when(devices.selectForUsageUpdate(9L)).thenReturn(current);
        var master = new DeviceServiceImpl(devices, mock(com.ruanzhu.doorhandle.module.device.mapper.DeviceCaptureAlertMapper.class), service);
        assertThatThrownBy(() -> master.removeEmployeeFromDevice(9L)).isInstanceOf(BusinessException.class);
        verify(devices).updateEmployeeId(9L, null);
    }

    @Test void maintenanceReceiptRetainsMaintenanceDeviceState() {
        Employee employee = new Employee(); employee.setEmployeeType("MAINTENANCE");
        Device device = new Device(); device.setId(9L); device.setStatus("MAINTENANCE");
        when(employees.selectForUsageReference(11L)).thenReturn(employee);
        when(devices.selectForUsageReference(9L)).thenReturn(device);
        when(devices.updateById(device)).thenReturn(1);
        assertThat(service.createRecordOnAssign(9L, 11L, "Maintenance")).isTrue();
        assertThat(device.getStatus()).isEqualTo("MAINTENANCE");
        assertThat(device.getEmployeeId()).isEqualTo(11L);
        var captured = org.mockito.ArgumentCaptor.forClass(DeviceUsageRecord.class);
        verify(service).save(captured.capture());
        assertThat(captured.getValue().getStatus()).isEqualTo("IN_USE");
    }

    @Test void failedAssignmentDeviceWriteRaisesConflictForTransactionRollback() {
        when(employees.selectForUsageReference(11L)).thenReturn(new Employee());
        when(devices.selectForUsageReference(9L)).thenReturn(new Device());
        assertThatThrownBy(() -> service.createRecordOnAssign(9L, 11L, "Assignment"))
                .isInstanceOf(BusinessException.class);
    }

    private static DeviceUsageRecord history() {
        DeviceUsageRecord value = new DeviceUsageRecord(); value.setId(41L); value.setVersion(3L);
        value.setEmployeeId(11L); value.setDeviceId(9L); value.setEmployeeName("Original employee");
        value.setEmployeeNumber("E-OLD"); value.setDeviceCode("D-OLD"); value.setStatus("RETURNED");
        return value;
    }
}
