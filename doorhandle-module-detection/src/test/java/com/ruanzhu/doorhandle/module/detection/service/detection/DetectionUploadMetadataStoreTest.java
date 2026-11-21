package com.ruanzhu.doorhandle.module.detection.service.detection;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionCaptureInfo;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionUploadFileRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionUploadMetadata;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.mock;

class DetectionUploadMetadataStoreTest {
    private final DetectionUploadMetadataStore store = new DetectionUploadMetadataStore(mock(JdbcTemplate.class), new ObjectMapper());

    @Test
    void snapshotUsesRegisteredFieldsAndListsImagesEvenWithoutTheirOwnNotes() {
        var capture = new DetectionCaptureInfo();
        capture.setCollector("EMP-0099");
        var metadata = new DetectionUploadMetadata("图片批次", "采集说明",
                List.of(new DetectionUploadMetadata.Image("门右/a.jpg","右边",Map.of("位置","右门"))));
        var document = store.document(capture, List.of(file("图片批次/门左/a.jpg"),file("图片批次/门右/a.jpg")), metadata);
        assertEquals("EMP-0099", document.at("/captureInfo/collector").asText());
        assertEquals("采集说明", document.path("notes").asText());
        assertEquals("门左/a.jpg", document.at("/images/0/path").asText());
        assertFalse(document.at("/images/0").has("notes"));
        assertEquals("门右/a.jpg", document.at("/images/1/path").asText());
        assertEquals("右门", document.at("/images/1/attributes/位置").asText());
    }

    @Test
    void rejectsUnselectedDuplicateOrNonRelativeReferencesAndMismatchedRoot() {
        var capture = new DetectionCaptureInfo();
        var files = List.of(file("批次/a.jpg"));
        for (String path : List.of("b.jpg", "../a.jpg", "C:/a.jpg")) {
            var metadata = new DetectionUploadMetadata("批次", null, List.of(new DetectionUploadMetadata.Image(path,null,null)));
            assertEquals(400, assertThrows(BusinessException.class, () -> store.document(capture, files, metadata)).getCode());
        }
        var selected = new DetectionUploadMetadata.Image("a.jpg",null,null);
        var duplicate = new DetectionUploadMetadata("批次",null,List.of(selected,selected));
        assertThrows(BusinessException.class, () -> store.document(capture, files, duplicate));
        var wrongDirectory = new DetectionUploadMetadata("另一批次",null,List.of());
        assertThrows(BusinessException.class, () -> store.document(capture, files, wrongDirectory));
    }

    private static DetectionUploadFileRequest file(String path) {
        var upload = new DetectionUploadFileRequest();
        upload.setRelativePath(path);
        upload.setFileName(path.substring(path.lastIndexOf('/')+1));
        return upload;
    }
}
