package com.ruanzhu.doorhandle.module.detection.service.detection;

import com.ruanzhu.doorhandle.common.BusinessException;
import java.text.Normalizer;

/** Originals and derived results share a unique batch under the actual uploader's personnel number. */
public final class UploadFolders {
    public static final String ROOT = "图片上传";
    public static final String SUPERVISORS = "主管上传", STAFF = "员工上传";
    private static final String ORIGINAL = "/Original/";
    private static final String IMAGES = "images/";
    private UploadFolders() {}

    public static String root(String base) { return base + "/" + ROOT + "/"; }

    public static boolean isImagePrefix(String prefix) {
        return prefix != null && prefix.endsWith(ORIGINAL + IMAGES);
    }

    public static String originalDirectory(String prefix) {
        return isImagePrefix(prefix) ? prefix.substring(0, prefix.length() - IMAGES.length()) : prefix;
    }

    public static String metadataKey(String imagePrefix) {
        String originalPrefix = originalDirectory(imagePrefix);
        if (originalPrefix == null || !originalPrefix.endsWith(ORIGINAL)) {
            throw new BusinessException(409, "原图目录不完整，暂无法保存元数据文件");
        }
        return originalPrefix + "metadata.json";
    }

    public static String batch(String base, boolean supervisor, String employeeNumber, String batchName, String taskId) {
        if (employeeNumber == null || !employeeNumber.matches("[\\p{L}\\p{N}_-]{1,50}"))
            throw new BusinessException(409, "上传账号缺少可用于 OSS 目录的有效工号，请核对人员绑定");
        if (taskId == null || !taskId.matches("det_[a-zA-Z0-9_]+")) throw new IllegalArgumentException("无效任务编号");
        String name = Normalizer.normalize(batchName, Normalizer.Form.NFKC)
                .replaceAll("[/\\\\\\p{Cc}]", "_").strip();
        String prefix = root(base) + (supervisor ? SUPERVISORS : STAFF) + "/" + employeeNumber + "/"
                + name + "_" + taskId + ORIGINAL + IMAGES;
        if (prefix.codePointCount(0,prefix.length())+22>255)
            throw new BusinessException(400,"批次目录名称过长，请缩短后上传");
        return prefix;
    }
}
