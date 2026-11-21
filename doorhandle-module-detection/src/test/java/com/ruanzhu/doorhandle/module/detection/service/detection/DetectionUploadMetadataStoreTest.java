package com.ruanzhu.doorhandle.module.detection.service.detection;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionCaptureInfo;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionUploadFileRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionUploadMetadata;
import com.ruanzhu.doorhandle.module.infra.service.OssStorageService;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.sql.ResultSet;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class DetectionUploadMetadataStoreTest {
    private final JdbcTemplate jdbc = mock(JdbcTemplate.class);
    private final OssStorageService oss = mock(OssStorageService.class);
    private final DetectionUploadMetadataStore store = new DetectionUploadMetadataStore(jdbc, new ObjectMapper(), oss);

    @Test
    void savesTheRegisteredJsonNextToImagesAndOnlyMarksAConfirmedWrite() throws Exception {
        String taskId = "det_1";
        String directory = "detection/图片上传/主管上传/SUP-0001/车门_det_1/Original/";
        String prefix = directory + "images/";
        String contents = "{\"schemaVersion\":1,\"notes\":\"原图资料\"}";
        long length = contents.getBytes(StandardCharsets.UTF_8).length;
        var row = mock(ResultSet.class);
        when(row.getString("payload_json")).thenReturn(contents);
        when(row.getString("state_code")).thenReturn(null, null, "OSS_STORED");
        when(jdbc.query(contains("FOR UPDATE"), org.mockito.ArgumentMatchers.<RowMapper<Object>>any(), eq(taskId)))
                .thenAnswer(call -> {
                    RowMapper<?> mapper = call.getArgument(1);
                    return List.of(mapper.mapRow(row, 0));
                });
        doAnswer(call -> {
            throw new IllegalStateException("OSS unavailable");
        }).doAnswer(call -> {
            InputStream input = call.getArgument(1);
            assertEquals(contents, new String(input.readAllBytes(), StandardCharsets.UTF_8));
            return null;
        }).when(oss).putObject(eq(directory + "metadata.json"), any(InputStream.class), eq(length), eq("application/json"));

        assertEquals(503, assertThrows(BusinessException.class, () -> store.storeInOss(taskId, prefix)).getCode());
        verify(jdbc, never()).update(contains("OSS_STORED"), eq(taskId));
        store.storeInOss(taskId, prefix);
        store.storeInOss(taskId, prefix);
        verify(jdbc, times(1)).update(contains("OSS_STORED"), eq(taskId));
        verify(oss, times(2)).putObject(eq(directory + "metadata.json"), any(InputStream.class), eq(length), eq("application/json"));
    }

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
