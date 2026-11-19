package com.ruanzhu.doorhandle.module.detection.service;

import com.ruanzhu.doorhandle.common.BusinessException;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class FolderTaskBoardTest {
    @Test void onlyImageDirectoriesCanBecomeAssignments() {
        for(var path:new String[]{"detection/","detection/采集 01/Original/"}) FolderTaskBoard.validatePrefix(path);
        for(var path:new String[]{"","other/","detection/../","detection/a//b/","detection/Result/","detection/folder-results/x/"})
            assertThrows(BusinessException.class,()->FolderTaskBoard.validatePrefix(path));
        assertTrue(FolderTaskBoard.imageKey("图一.JPG"));
        assertFalse(FolderTaskBoard.imageKey("detection_results.json"));
    }
}
