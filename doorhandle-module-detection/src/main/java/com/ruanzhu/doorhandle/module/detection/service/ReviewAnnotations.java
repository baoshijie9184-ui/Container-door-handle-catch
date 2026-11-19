package com.ruanzhu.doorhandle.module.detection.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionTaskMapper;
import com.ruanzhu.doorhandle.module.detection.security.DetectionTaskAccessPolicy;
import com.ruanzhu.doorhandle.module.detection.service.detection.DetectionQualityWorkflow;
import com.ruanzhu.doorhandle.module.infra.service.OssPreviewStorage;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;
import javax.imageio.ImageIO;
import javax.imageio.stream.MemoryCacheImageInputStream;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.*;

@Service
@RequiredArgsConstructor
public class ReviewAnnotations {
    public record Target(String label, List<Double> box) {}
    public record Save(String sourceKey, String basis, Long revision, List<Target> targets) {}
    public record Edition(long revision, long userId, String employee, String savedAt, int width, int height, List<Target> targets) {}
    public record Model(String basis, int width, int height, List<Target> targets) {}
    public record View(boolean editable, Edition edition, Model model) {}
    private static final Set<String> LABELS = Set.of("Normal","Bent","Deformed","Rusty","Missing","Compromised");
    private final DetectionTaskMapper tasks;
    private final DetectionTaskAccessPolicy access;
    private final BusinessUserDirectory users;
    private final JdbcTemplate jdbc;
    private final TransactionTemplate transactions;
    private final ObjectMapper json;
    private final OssPreviewStorage storage;
    @Value("${folder.results.dir:}") private String folderResults;

    public View get(String id, String sourceKey, boolean withModel) {
        var task = task(id, sourceKey, false);
        var actor = users.authenticated();
        return new View(editable(task, actor), edition(task, sourceKey), withModel ? model(task, sourceKey) : null);
    }

    public View save(String id, Save input) {
        if (input == null || input.revision() == null || input.revision() < 0 || input.basis() == null)
            throw new BusinessException(400, "缺少标注版本");
        var initial = task(id, input.sourceKey(), false);
        var actor = users.authenticated();
        requireEditor(initial, actor);
        var model = model(initial, input.sourceKey());
        if (!model.basis().equals(input.basis())) throw conflict();
        validate(input.targets(), model);
        return transactions.execute(status -> {
            var currentActor = users.lockCurrent(actor.userId(), actor.username());
            var locked = task(id, input.sourceKey(), true);
            requireEditor(locked, currentActor);
            if (!run(locked).equals(run(initial))) throw conflict();
            var previous = edition(locked, input.sourceKey());
            long revision = previous == null ? 0 : previous.revision();
            if (input.revision() != revision) {
                if (previous != null && revision-1 == input.revision() && previous.userId() == currentActor.userId()
                        && previous.targets().equals(input.targets())) return new View(true,previous,model);
                throw conflict();
            }
            var saved = new Edition(revision+1, currentActor.userId(), currentActor.username(), Instant.now().toString(),
                    model.width(), model.height(), List.copyOf(input.targets()));
            jdbc.update("UPDATE detection_task SET review_annotations_json=JSON_SET(COALESCE(review_annotations_json,JSON_OBJECT()),?,CAST(? AS JSON)) WHERE id=?",
                    path(locked,input.sourceKey()), json.valueToTree(saved).toString(), locked.getId());
            return new View(true, saved, model);
        });
    }

    private DetectionTask task(String id, String key, boolean lock) {
        var query = new LambdaQueryWrapper<DetectionTask>().eq(DetectionTask::getTaskId,id);
        if (lock) query.last("FOR UPDATE");
        var task = tasks.selectOne(query);
        if (task == null) throw new BusinessException(404, "任务不存在或无访问权限");
        access.assertCanAccess(task, SecurityContextHolder.getContext().getAuthentication());
        if (key == null || key.isBlank() || key.length()>1024 || !contains(task.getOriginalImageKeysJson(), key))
            throw new BusinessException(404, "原图不属于当前任务");
        return task;
    }

    private boolean editable(DetectionTask task, BusinessUserDirectory.Identity actor) {
        try { DetectionQualityWorkflow.assertReviewable(task); }
        catch (BusinessException closed) { return false; }
        if (actor.supervisor()) return true;
        Long assigned = jdbc.queryForObject("SELECT assignee_user_id FROM detection_task WHERE id=?", Long.class,task.getId());
        return assigned != null ? assigned == actor.userId() : actor.username().equals(task.getAssignee());
    }
    private void requireEditor(DetectionTask task, BusinessUserDirectory.Identity actor) {
        DetectionQualityWorkflow.assertReviewable(task);
        if (!editable(task,actor)) throw new BusinessException(403,"仅受派质检员工或主管可调整标注");
    }
    private String run(DetectionTask task) {
        return task.getTaskId()+"\n"+task.getDispatchId()+"\n"+task.getLastFinishedEventId()+"\n"+task.getResultJsonOssKey();
    }
    private String path(DetectionTask task, String key) {
        return "$.\""+digest(run(task)+"\n"+key)+"\"";
    }
    private static String digest(String text) {
        try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(text.getBytes(StandardCharsets.UTF_8))); }
        catch (java.security.NoSuchAlgorithmException impossible) { throw new IllegalStateException(impossible); }
    }
    private Edition edition(DetectionTask task, String key) {
        String value = jdbc.queryForObject("SELECT JSON_EXTRACT(review_annotations_json,?) FROM detection_task WHERE id=?",
                String.class,path(task,key),task.getId());
        try { return value == null ? null : json.readValue(value, Edition.class); }
        catch (IOException e) { throw new BusinessException(409,"已保存的人工标注读取失败"); }
    }
    private boolean contains(String keys, String key) {
        try {
            if (keys != null) for (var node : json.readTree(keys)) if (key.equals(node.textValue())) return true;
            return false;
        } catch (IOException e) { throw new BusinessException(409,"任务图片清单无法核对"); }
    }
    private static BusinessException conflict() { return new BusinessException(409,"标注版本已变化，请重新打开后调整"); }

    static void validate(List<Target> targets, Model model) {
        if (targets == null || targets.size()!=model.targets().size() || targets.size()>300)
            throw new BusinessException(400,"请保留当前图片的检测框数量");
        for (var target : targets) {
            if (target == null || target.label()==null || !LABELS.contains(target.label()) || target.box()==null || target.box().size()!=4)
                throw new BusinessException(400,"框或类别无效");
            var b=target.box();
            if (b.stream().anyMatch(n -> n==null || !Double.isFinite(n)) || b.get(0)<0 || b.get(1)<0
                    || b.get(2)>model.width() || b.get(3)>model.height() || b.get(0)>=b.get(2) || b.get(1)>=b.get(3))
                throw new BusinessException(400,"标注框须位于图片内且有可见面积");
        }
    }

    private Model model(DetectionTask task, String sourceKey) {
        if (task.getResultJsonOssKey()==null) throw new BusinessException(409,"此任务没有模型坐标文件");
        try {
            JsonNode report;
            try (var stream=open(task,task.getResultJsonOssKey())) {
                byte[] bytes=stream.readNBytes(16*1024*1024+1);
                if (bytes.length>16*1024*1024) throw new BusinessException(413,"坐标文件过大");
                report=json.readTree(bytes);
            }
            JsonNode row=null;
            for (var item : report.path("results")) if (sourceKey.equals(item.path("sourceKey").textValue())) {
                if (row!=null) throw new BusinessException(409,"模型记录中有多份同名原图");
                row=item;
            }
            if (row==null || !row.path("detections").isArray() || row.path("detections").size()>300)
                throw new BusinessException(409,"这张图片缺少可编辑的模型坐标");
            String preview=row.path("previewKey").asText("");
            if (preview.isBlank() || !contains(task.getPreviewImageKeysJson(),preview))
                throw new BusinessException(409,"没有找到本次推理的标注图");
            int width,height;
            try (var stream=open(task,preview); var input=new MemoryCacheImageInputStream(stream)) {
                var readers=ImageIO.getImageReaders(input);
                if (!readers.hasNext()) throw new IOException("unreadable image");
                var reader=readers.next();
                try { reader.setInput(input,true,true); width=reader.getWidth(0); height=reader.getHeight(0); }
                finally { reader.dispose(); }
            }
            if (width<1 || height<1 || (long)width*height>40_000_000) throw new IOException("unsupported image size");
            var targets=new ArrayList<Target>();
            for (var d : row.path("detections")) {
                var box=new ArrayList<Double>();
                for (var n : d.path("box")) { if (!n.isNumber()) throw new IOException("invalid coordinate"); box.add(n.doubleValue()); }
                targets.add(new Target(d.path("label").asText(),box));
            }
            var result=new Model(digest(run(task)+"\n"+sourceKey+"\n"+row+"\n"+width+"x"+height),width,height,targets);
            validate(targets,result);
            return result;
        } catch (BusinessException expected) { throw expected; }
        catch (Exception e) { throw new BusinessException(409,"当前无法读取模型坐标或标注图"); }
    }

    private InputStream open(DetectionTask task, String key) throws IOException {
        if (key.startsWith("detection/folder-results/") && folderResults!=null && !folderResults.isBlank()) {
            String prefix="detection/folder-results/"+task.getTaskId()+"/"+task.getDispatchId()+"/";
            if (!key.startsWith(prefix) || !task.getTaskId().matches("det_folder_[a-f0-9]{32}") ||
                    task.getDispatchId()==null || !task.getDispatchId().matches("[a-f0-9-]{36}")) throw new IOException("wrong local run");
            String name=key.substring(prefix.length());
            if (name.isBlank() || name.equals(".") || name.equals("..") || name.contains("/") || name.contains("\\")) throw new IOException("invalid result name");
            return Files.newInputStream(Path.of(folderResults,task.getTaskId(),task.getDispatchId(),name));
        }
        // Both keys originate in validated task-owned result records. Close the OSS response with the stream.
        var object=storage.open(key,false);
        return object.getObjectContent();
    }
}
