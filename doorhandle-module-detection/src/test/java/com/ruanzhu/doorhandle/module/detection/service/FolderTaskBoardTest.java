package com.ruanzhu.doorhandle.module.detection.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.contracts.agent.AgentUserDirectory;
import com.ruanzhu.doorhandle.contracts.organization.EmployeeAccountNumbers;
import com.ruanzhu.doorhandle.contracts.organization.EmployeeNumberDirectory;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.detection.security.DetectionTaskAccessPolicy;
import com.ruanzhu.doorhandle.module.detection.service.detection.DetectionUploadMetadataStore;
import com.ruanzhu.doorhandle.module.detection.service.impl.DetectionTaskServiceImpl;
import com.ruanzhu.doorhandle.module.infra.service.OssPreviewStorage;
import com.ruanzhu.doorhandle.module.infra.service.OssStorageService;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.jdbc.core.namedparam.SqlParameterSource;
import java.util.List;
import java.util.HashMap;
import java.util.Map;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class FolderTaskBoardTest {
    @Test void onlyImageDirectoriesCanBecomeAssignments() {
        for(var path:new String[]{"detection/","detection/采集 01/Original/"}) FolderTaskBoard.validatePrefix(path);
        for(var path:new String[]{"","other/","detection/../","detection/a//b/","detection/Result/","detection/folder-results/x/"})
            assertThrows(BusinessException.class,()->FolderTaskBoard.validatePrefix(path));
        assertTrue(FolderTaskBoard.imageKey("图一.JPG"));
        assertFalse(FolderTaskBoard.imageKey("detection_results.json"));
    }

    @Test void verificationRowsAndTotalsExcludeLinkedUploadsButUploadHistoryRemainsAvailable() {
        var db=mock(NamedParameterJdbcTemplate.class);
        var users=mock(BusinessUserDirectory.class);
        var access=mock(DetectionTaskAccessPolicy.class);
        when(access.currentSqlScope("t.")).thenReturn(new DetectionTaskAccessPolicy.SqlScope("1=1",Map.of()));
        when(access.qualityAssigneeSql("t.",":actor",":username")).thenReturn("t.assignee_user_id=:actor");
        when(users.authenticated()).thenReturn(new BusinessUserDirectory.Identity(1L,"SUP-0001",true),
                new BusinessUserDirectory.Identity(2L,"DET-0001",false),
                new BusinessUserDirectory.Identity(1L,"SUP-0001",true));
        when(db.queryForObject(anyString(),any(SqlParameterSource.class),eq(Long.class))).thenReturn(0L);
        when(db.queryForList(anyString(),any(SqlParameterSource.class))).thenReturn(List.of());
        var board=new FolderTaskBoard(db,mock(OssPreviewStorage.class),mock(DetectionTaskServiceImpl.class),
                access,users,mock(EmployeeAccountNumbers.class),mock(EmployeeNumberDirectory.class),
                mock(AgentUserDirectory.class),mock(OssStorageService.class),mock(DetectionUploadMetadataStore.class),
                mock(DetectionWorkUnitAudit.class),new ObjectMapper());

        board.list("WAITING_CHECK",null,null,false,false,null,"verification",null,1,20);
        board.list(null,null,null,true,false,null,null,"verification",1,20);
        board.uploads("team",null,null,null,false,1,20);

        var counts=ArgumentCaptor.forClass(String.class);
        var rows=ArgumentCaptor.forClass(String.class);
        verify(db,times(3)).queryForObject(counts.capture(),any(SqlParameterSource.class),eq(Long.class));
        verify(db,times(3)).queryForList(rows.capture(),any(SqlParameterSource.class));
        for(int i=0;i<2;i++){
            String where=counts.getAllValues().get(i).substring("SELECT COUNT(*)".length());
            assertTrue(where.contains("NOT EXISTS ("));
            assertTrue(where.contains("a.source_batch_id=t.task_id"));
            assertTrue(where.contains("BINARY t.source_oss_prefix=BINARY f.source_oss_prefix"));
            assertTrue(rows.getAllValues().get(i).contains(where));
        }
        assertTrue(counts.getAllValues().get(1).contains("t.assignee_user_id=:actor"));
        assertTrue(counts.getAllValues().get(1).contains("'FOLLOW_UP'"));
        assertFalse(counts.getAllValues().get(2).contains("a.source_batch_id=t.task_id"));
        assertTrue(rows.getAllValues().get(2).contains("AS formalVerificationTaskId"));

        var missingImages = new HashMap<String,Object>(Map.of("flow","RECHECK_REQUIRED","recheckOriginalKeys","[]"));
        var verifiedImages = new HashMap<String,Object>(Map.of("flow","RECHECK_REQUIRED","recheckOriginalKeys","[\"detection/Original/images/01.jpg\"]"));
        when(db.queryForList(anyString(),any(SqlParameterSource.class))).thenReturn(List.of(missingImages,verifiedImages));
        var followUp = board.list("FOLLOW_UP",null,null,false,false,null,"verification",null,1,20).items();
        assertTrue(followUp.get(0).get("recheckBlockedReason").toString().contains("原图清单"));
        assertNull(followUp.get(1).get("recheckBlockedReason"));
        assertFalse(followUp.get(0).containsKey("recheckOriginalKeys"));
        assertFalse(followUp.get(1).containsKey("recheckOriginalKeys"));
    }
}
