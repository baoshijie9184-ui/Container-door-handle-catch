package com.ruanzhu.doorhandle.module.detection.service.detection;

import com.ruanzhu.doorhandle.common.BusinessException;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class UploadFoldersTest {
    @Test void stableOwnerAndUniqueBatch() {
        assertEquals("detection/图片上传/员工上传/DET-0001/批次A_det_one/Original/",
            UploadFolders.batch("detection",false,"DET-0001","批次A","det_one"));
        assertNotEquals(UploadFolders.batch("detection",true,"SUP-0001","A","det_one"),
            UploadFolders.batch("detection",true,"SUP-0001","A","det_two"));
        assertThrows(BusinessException.class,()->UploadFolders.batch("detection",false,"../DET-0001","A","det_one"));
        assertThrows(BusinessException.class,()->UploadFolders.batch("detection",true,null,"A","det_one"));
    }
}
