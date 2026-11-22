package com.ruanzhu.doorhandle.module.ai.action;

import com.ruanzhu.doorhandle.contracts.agent.AgentRequestRestriction;
import com.ruanzhu.doorhandle.contracts.agent.DetectionCreationApi;
import com.ruanzhu.doorhandle.contracts.agent.WorkspaceDetectionImagesApi;

import java.math.BigDecimal;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Set;
import java.util.regex.Pattern;

/** Interprets only recent, direct human commands. Everything outside this grammar needs the usual confirmation. */
final class FastActionIntent {
    private static final String TASK_ID = "[A-Za-z0-9_-]{1,128}";
    private static final String FILE_ID = "[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}";
    private static final String PREFIX = "(?:请(?:你|帮我)?\\h*)?(?:现在\\h*)?(?:(?:立即|直接)\\h*)?";
    private static final String RETRY = "(?:重试(?:检测)?|重新检测|启动复检)";
    private static final Pattern RETRY_FIRST = Pattern.compile("^" + PREFIX + RETRY + "\\h*(?:任务\\h*)?[:：]?\\h*`?(" + TASK_ID + ")`?[。！.!]?$");
    private static final Pattern TASK_FIRST = Pattern.compile("^" + PREFIX + "(?:把\\h*)?(?:任务\\h*)?`?(" + TASK_ID + ")`?\\h+" + RETRY + "[。！.!]?$");
    private static final Pattern CREATE = Pattern.compile("^" + PREFIX + "(?:创建(?:新)?检测(?:任务)?|新建检测任务|提交检测任务)[:：。！.!]?$");
    private static final Pattern FILE = Pattern.compile("^(?:@file:)?(" + FILE_ID + ")$");
    private static final Pattern BUSINESS_FILE = Pattern.compile("^(" + TASK_ID + ")/(?:@file:)?(" + FILE_ID + ")$");
    private static final Pattern NEGATION = Pattern.compile("不要|不必|不用|不允许|不得|禁止|暂不|先别|仅查询|只查询|暂缓|取消");
    private static final Set<String> CAPTURE_FIELDS = Set.of("采集日期","区域","采集人","设备","批次文件夹","检测模型编号");
    private static final BigDecimal DEFAULT_THRESHOLD = new BigDecimal("0.5");

    private FastActionIntent() {}

    record Creation(Set<String> files, Set<WorkspaceDetectionImagesApi.BusinessReference> businessFiles,
                    DetectionCreationApi.Capture capture, int modelId, BigDecimal threshold) {
        boolean matches(DetectionCreationApi.Preview preview) {
            if (!capture.equals(preview.capture()) || modelId != preview.model().id() || threshold.compareTo(preview.threshold()) != 0) return false;
            var privateImages = new HashSet<String>();
            var businessImages = new HashSet<WorkspaceDetectionImagesApi.BusinessReference>();
            for (var image : preview.images()) {
                if (image.origin() == null) privateImages.add(image.fileId());
                else businessImages.add(new WorkspaceDetectionImagesApi.BusinessReference(image.origin().taskId(), image.origin().fileId()));
            }
            return files.equals(privateImages) && businessFiles.equals(businessImages)
                    && preview.images().size() == files.size() + businessFiles.size();
        }
    }

    static String retryTask(String directHumanInput) {
        if (!unrestricted(directHumanInput)) return null;
        String text = directHumanInput.strip();
        var retryFirst = RETRY_FIRST.matcher(text);
        if (retryFirst.matches()) return retryFirst.group(1);
        var taskFirst = TASK_FIRST.matcher(text);
        return taskFirst.matches() ? taskFirst.group(1) : null;
    }

    static Creation creation(String directHumanInput) {
        if (!unrestricted(directHumanInput)) return null;
        String[] lines = directHumanInput.strip().split("[\\r\\n;；]+", -1);
        if (lines.length < 2 || !CREATE.matcher(lines[0].strip()).matches()) return null;
        var fields = new HashMap<String, String>();
        var files = new HashSet<String>();
        var businessFiles = new HashSet<WorkspaceDetectionImagesApi.BusinessReference>();
        for (int index = 1; index < lines.length; index++) {
            String line = lines[index].strip();
            if (line.startsWith("@file:")) {
                if (!addPrivateFiles(line, files)) return null;
                continue;
            }
            String[] pair = line.split("[:：]", 2);
            if (pair.length != 2 || pair[1].isBlank()) return null;
            String field = pair[0].strip();
            String value = pair[1].strip();
            switch (field) {
                case "图片", "原图" -> { if (!addPrivateFiles(value, files)) return null; }
                case "业务原图" -> { if (!addBusinessFiles(value, businessFiles)) return null; }
                default -> {
                    if ((!CAPTURE_FIELDS.contains(field) && !"阈值".equals(field)) || fields.putIfAbsent(field, value) != null) return null;
                }
            }
        }
        int imageCount = files.size() + businessFiles.size();
        if (imageCount < 1 || imageCount > 200 || !fields.keySet().containsAll(CAPTURE_FIELDS)) return null;
        String model = fields.get("检测模型编号");
        String threshold = fields.get("阈值");
        if (!model.matches("[1-9][0-9]{0,9}") || threshold != null && !threshold.matches("(?:0(?:\\.[0-9]{1,8})?|1(?:\\.0{1,8})?)")) return null;
        try {
            var capture = new DetectionCreationApi.Capture(fields.get("采集日期"), fields.get("区域"), fields.get("采集人"),
                    fields.get("设备"), fields.get("批次文件夹"));
            return new Creation(Set.copyOf(files), Set.copyOf(businessFiles), capture, Integer.parseInt(model),
                    threshold == null ? DEFAULT_THRESHOLD : new BigDecimal(threshold));
        } catch (NumberFormatException invalidModel) {
            return null;
        }
    }

    private static boolean addPrivateFiles(String value, Set<String> files) {
        for (String token : value.split("[\\s,，、]+")) {
            var matcher = FILE.matcher(token);
            if (!matcher.matches() || !files.add(matcher.group(1))) return false;
        }
        return true;
    }

    private static boolean addBusinessFiles(String value, Set<WorkspaceDetectionImagesApi.BusinessReference> files) {
        for (String token : value.split("[\\s,，、]+")) {
            var matcher = BUSINESS_FILE.matcher(token);
            if (!matcher.matches() || !files.add(new WorkspaceDetectionImagesApi.BusinessReference(matcher.group(1),matcher.group(2)))) return false;
        }
        return true;
    }

    private static boolean unrestricted(String text) {
        return text != null && !text.isBlank() && text.length() <= 8000 && !NEGATION.matcher(text).find()
                && AgentRequestRestriction.detect(text).isEmpty();
    }
}
