package com.ruanzhu.doorhandle.module.ai.evolution;

import jakarta.validation.constraints.*;
import java.util.List;
import java.util.Map;

public final class SkillDtos {
    private SkillDtos() {}
    public record Draft(@NotBlank @Pattern(regexp="[a-z][a-z0-9-]{2,63}") String name,
            @NotBlank @Pattern(regexp="INSPECTOR|SUPERVISOR") String targetRole,
            @NotBlank @Size(min=4,max=300) String description,
            @NotBlank @Size(min=40,max=6000) String instructions,
            @NotEmpty @Size(max=12) List<@NotBlank String> tools,
            @NotBlank @Pattern(regexp="[A-Za-z0-9_-]{1,128}") String sourceRunId,
            @NotBlank @Pattern(regexp="[A-Za-z0-9_-]{8,64}") String requestId,
            @Null(message="外部 Skill 上传已移除") String sourceImportId) {
        public Draft(String name,String targetRole,String description,String instructions,List<String> tools,String sourceRunId,String requestId){this(name,targetRole,description,instructions,tools,sourceRunId,requestId,null);}
    }
    public record Command(@Min(1) int expectedRevision,@NotBlank @Size(max=500) String reason) {}
    public record Decision(@Min(1) int expectedRevision,@Pattern(regexp="APPROVE|REJECT") String decision,
            @NotBlank @Size(max=500) String reason,@AssertTrue boolean businessReviewed,@AssertTrue boolean privacyReviewed) {}
    public record Rollback(@Min(1) int expectedRevision,@Min(1) int targetVersion,@NotBlank @Size(max=500) String reason) {}
    public record AvailableSkill(String skillId,String name,int version,String description,List<String> tools) {}
    public record LoadedSkill(AvailableSkill metadata,String targetRole,String instructions,String sha256) {}
    public record Version(int version,String status,String description,String instructions,List<String> tools,String sha256,
            Map<String,Object> evidence,String sourceRunId,String reviewReason,String createdAt) {}
    public record View(String skillId,long ownerUserId,String name,String targetRole,int revision,int latestVersion,Integer activeVersion,
            String lifecycle,long useCount,String lastUsedAt,List<Version> versions,List<Map<String,Object>> evaluations,List<Map<String,Object>> audit) {}
}
