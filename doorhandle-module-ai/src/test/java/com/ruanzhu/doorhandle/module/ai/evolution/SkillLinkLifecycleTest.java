package com.ruanzhu.doorhandle.module.ai.evolution;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.ai.journal.AgentJournal;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.*;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class SkillLinkLifecycleTest {
    @TempDir Path workspace;
    AgentActor alice=new AgentActor(1,"alice",AgentActor.Role.INSPECTOR),bob=new AgentActor(2,"bob",AgentActor.Role.INSPECTOR),boss=new AgentActor(3,"boss",AgentActor.Role.SUPERVISOR);
    JdbcTemplate jdbc;org.springframework.transaction.PlatformTransactionManager manager;BusinessUserDirectory users;SkillEvolutionService service;SkillLinkStorage storage;ObjectMapper json=new ObjectMapper().findAndRegisterModules();
    String downloadId="download-"+UUID.randomUUID();
    @BeforeEach void setup()throws Exception{
        var source=new DriverManagerDataSource("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=MySQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1","sa","");jdbc=new JdbcTemplate(source);
        String ddl=Files.readString(Path.of("../sql/mysql/migration-V23-agent-skill-evolution.sql")).replace(" JSON "," TEXT ").replace(" ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin","").replaceAll("(?m)^\\s*(?:UNIQUE )?KEY .*\\n","").replaceAll(",\\s*\\)","\n)");
        for(String sql:ddl.split(";"))if(!sql.isBlank())jdbc.execute(sql);
        jdbc.execute("ALTER TABLE agent_skill_version MODIFY source_run_id VARCHAR(128) NULL");jdbc.execute("ALTER TABLE agent_skill_version ADD COLUMN source_type VARCHAR(32) NOT NULL DEFAULT 'RUN'");jdbc.execute("ALTER TABLE agent_skill_version ADD COLUMN source_import_id VARCHAR(64) NULL");
        jdbc.execute("CREATE TABLE agent_skill_download(download_id VARCHAR(64) PRIMARY KEY,owner_user_id BIGINT,status VARCHAR(32),target_role VARCHAR(32),manifest_json TEXT,manifest_sha256 CHAR(64),target_skill_id VARCHAR(64),expected_skill_revision INT,skill_id VARCHAR(64),request_id VARCHAR(64),request_sha256 CHAR(64),source_url VARCHAR(1000),created_at DATETIME,updated_at DATETIME)");
        String cleanupDdl=Files.readString(Path.of("../sql/mysql/migration-V29-skill-storage-cleanup.sql")).replace(" ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin","").replaceAll("(?m)^\\s*(?:UNIQUE )?KEY .*\\n","").replaceAll(",\\s*\\)","\n)");
        for(String statement:cleanupDdl.split(";"))if(!statement.isBlank())jdbc.execute(statement);
        String leaseDdl=Files.readString(Path.of("../sql/mysql/migration-V46-skill-download-leases.sql")).replace(" COLLATE utf8mb4_bin","").replace(" ENGINE=InnoDB DEFAULT CHARSET=utf8mb4","").replaceAll("(?m)^\\s*(?:UNIQUE )?KEY .*\\n","").replaceAll(",\\s*\\)","\n)");
        for(String statement:leaseDdl.split(";"))if(!statement.isBlank())jdbc.execute(statement);
        users=mock(BusinessUserDirectory.class);for(var actor:List.of(alice,bob,boss))when(users.current(actor.userId(),actor.username())).thenReturn(new BusinessUserDirectory.Identity(actor.userId(),actor.username(),actor.supervisor()));
        manager=new DataSourceTransactionManager(source);service=new SkillEvolutionService(jdbc,manager,json,users,mock(AgentJournal.class));storage=new SkillLinkStorage(jdbc,json,workspace.toString());service.linkStorage(storage);
        Path path=storage.directory(1,downloadId);Files.createDirectories(path);
        String body="Read publicly available references using already registered tools and verify every claim. Any included scripts are archived and must never run.";
        String raw="---\nname: fixture-reader\ndescription: Verified documentation reading skill\n---\n\n"+body;
        byte[] bytes=raw.getBytes(StandardCharsets.UTF_8);Files.write(path.resolve("SKILL.md"),bytes);
        Map<String,Object> manifest=Map.ofEntries(Map.entry("sourceType","LINK"),Map.entry("sourceUrl","https://github.com/fixtures/skills/tree/main/skills/fixture-reader"),Map.entry("resolvedUrl","https://github.com/fixtures/skills/tree/"+"a".repeat(40)+"/skills/fixture-reader"),Map.entry("commit","a".repeat(40)),Map.entry("name","fixture-reader"),Map.entry("description","Verified documentation reading skill"),Map.entry("instructions",body),Map.entry("files",List.of(Map.of("path","SKILL.md","bytes",bytes.length,"sha256",HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes))))),Map.entry("licenses",Map.of("LICENSE","Apache License Version 2.0")),Map.entry("license","Apache-2.0"),Map.entry("provenanceVerified",true),Map.entry("scriptsExecutable",false),Map.entry("resourcesReadable",false));
        Files.writeString(path.resolve("manifest.json"),json.writeValueAsString(manifest));jdbc.update("INSERT INTO agent_skill_download(download_id,owner_user_id,status,target_role,manifest_json,manifest_sha256) VALUES(?,1,'DOWNLOADED','INSPECTOR',?,?)",downloadId,json.writeValueAsString(manifest),storage.digest(manifest));
    }
    SkillDtos.View create(){return service.createLinked(alice,downloadId,"INSPECTOR");}
    SkillDtos.View publish(){var view=create();view=service.evaluate(alice,view.skillId(),view.revision());view=service.submit(alice,view.skillId(),view.revision());return service.decide(boss,view.skillId(),new SkillDtos.Decision(view.revision(),"APPROVE","核对来源许可及仅正文参考的适用性",true,true));}
    @Test void downloadedDraftIsPrivateAndRequiresEvalThenIndependentApproval(){
        var view=create();assertThat(view.versions().get(0).evidence()).containsEntry("sourceType","LINK");
        assertThat(service.createLinked(alice,downloadId,"INSPECTOR").skillId()).isEqualTo(view.skillId());
        assertThat(service.repository(alice).getAllSkills()).isEmpty();assertThatThrownBy(()->service.get(bob,view.skillId())).hasMessageContaining("无权限");
        assertThatThrownBy(()->service.submit(alice,view.skillId(),view.revision())).hasMessageContaining("Eval");
        var evaluated=service.evaluate(alice,view.skillId(),view.revision());assertThat(evaluated.evaluations().get(0).get("result").toString()).contains("LINK_INSTRUCTIONS_ONLY");
        assertThat(service.repository(alice).getAllSkills()).isEmpty();
    }
    @Test void approvedLinkedSkillIsOnlyAvailableToInstallingAccountAndUninstallRevokesLoading(){
        var view=publish();assertThat(service.repository(alice).getAllSkills()).hasSize(1);assertThat(service.availableSkills(alice)).hasSize(1);
        assertThat(service.repository(bob).getAllSkills()).isEmpty();assertThat(service.availableSkills(bob)).isEmpty();
        assertThat(service.commandSkill(alice,"fixture-reader",false,null,null).instructions()).contains("must never run");
        assertThatThrownBy(()->service.commandSkill(bob,"fixture-reader",false,null,null)).hasMessageContaining("不可用");
        var archived=service.uninstallLinked(alice,view.skillId(),new SkillDtos.Command(view.revision(),"本人明确卸载"));
        assertThat(archived.activeVersion()).isNull();assertThat(service.repository(alice).getAllSkills()).isEmpty();assertThat(archived.versions()).hasSize(1);
        assertThat(Files.exists(storage.directory(1,downloadId).resolve("SKILL.md"))).isTrue();assertThat(archived.audit().toString()).contains("UNINSTALL_LINK");
    }
    @Test void tamperedFileCannotPassEvalOrLoadThroughExistingPublishedPointer()throws Exception{
        var view=publish();Files.writeString(storage.directory(1,downloadId).resolve("SKILL.md"),"replaced content");
        assertThatThrownBy(()->service.repository(alice)).hasMessageContaining("摘要");assertThatThrownBy(()->service.commandSkill(alice,"fixture-reader",false,null,null)).hasMessageContaining("摘要");
    }
    @Test void foreignPackageRoleEscalationAndAuditFailureCannotCreateUsableSkill(){
        assertThatThrownBy(()->service.createLinked(bob,downloadId,"INSPECTOR"));assertThatThrownBy(()->service.createLinked(alice,downloadId,"SUPERVISOR")).hasMessageContaining("角色");
        jdbc.execute("DROP TABLE agent_skill_audit");assertThatThrownBy(this::create);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_learned_skill",Long.class)).isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_skill_version",Long.class)).isZero();
    }
    @Test void sourcePolicyAcceptsMarketFormatsButDoesNotTreatThemAsVerifiedContents(){
        SkillLinkService.validateUrl("https://github.com/anthropics/skills/tree/main/skills/skill-creator");
        SkillLinkService.validateUrl("https://modelscope.cn/skills/@anthropics/skill-creator");
        SkillLinkService.validateUrl("https://modelscope.cn/skills/@unknown/example");SkillLinkService.validateUrl("https://skills.sh/anthropics/skills/skill-creator");
        for(String url:List.of("http://github.com/a/b/tree/main/skill","https://github.com:443/a/b/tree/main/skill","https://github.com/a/b/tree/main/../skill","https://github.com/a/b/tree/main/skill?token=secret","https://modelscope.cn/skills/@unknown/../example","https://skills.sh:443/anthropics/skills/skill-creator"))assertThatThrownBy(()->SkillLinkService.validateUrl(url)).hasMessageContaining("公开");
    }
    String upgradedPackage(SkillDtos.View view,String commit,String addition)throws Exception{
        String next="download-"+UUID.randomUUID();var manifest=new LinkedHashMap<String,Object>(storage.inspect(1,downloadId));
        String body=(String)manifest.get("instructions");body+=addition;String raw="---\nname: fixture-reader\ndescription: Verified documentation reading skill\n---\n\n"+body;
        byte[] bytes=raw.getBytes(StandardCharsets.UTF_8);Path directory=storage.directory(1,next);Files.createDirectories(directory);Files.write(directory.resolve("SKILL.md"),bytes);
        manifest.put("commit",commit);manifest.put("resolvedUrl","https://github.com/fixtures/skills/tree/"+commit+"/skills/fixture-reader");manifest.put("instructions",body);manifest.put("files",List.of(Map.of("path","SKILL.md","bytes",bytes.length,"sha256",HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes)))));
        Files.writeString(directory.resolve("manifest.json"),json.writeValueAsString(manifest));
        jdbc.update("INSERT INTO agent_skill_download(download_id,owner_user_id,status,target_role,manifest_json,manifest_sha256,target_skill_id,expected_skill_revision) VALUES(?,1,'DOWNLOADED','INSPECTOR',?,?,?,?)",next,json.writeValueAsString(manifest),storage.digest(manifest),view.skillId(),view.revision());return next;
    }
    @Test void upgradeAddsFrozenVersionPreservesPublishedPointerAndSupportsReviewedRollbackAndDiff()throws Exception{
        var first=publish();String next=upgradedPackage(first,"b".repeat(40),"\nCheck the cited publication date before answering.");
        var second=service.createLinked(alice,next,"INSPECTOR");assertThat(second.skillId()).isEqualTo(first.skillId());assertThat(second.latestVersion()).isEqualTo(2);assertThat(second.activeVersion()).isEqualTo(1);
        assertThat(service.repository(alice).getAllSkills().get(0).getSkillContent()).doesNotContain("publication date");
        var diff=service.compareLinked(alice,second.skillId(),1,2);assertThat(diff.changedFiles()).containsExactly("SKILL.md");assertThat(diff.addedLines()).isEqualTo(1);assertThat(diff.removedLines()).isZero();assertThat(diff.lines().get(0).text()).contains("publication date");
        assertThatThrownBy(()->service.compareLinked(boss,first.skillId(),1,2)).hasMessageContaining("无权限");
        second=service.evaluate(alice,second.skillId(),second.revision());second=service.submit(alice,second.skillId(),second.revision());
        assertThat(service.compareLinked(boss,second.skillId(),1,2).contentChanged()).isTrue();
        second=service.decide(boss,second.skillId(),new SkillDtos.Decision(second.revision(),"APPROVE","来源与差异已经核对",true,true));assertThat(second.activeVersion()).isEqualTo(2);
        var rolled=service.rollback(boss,second.skillId(),new SkillDtos.Rollback(second.revision(),1,"恢复审核旧版本"));assertThat(rolled.activeVersion()).isEqualTo(1);
        assertThat(service.get(alice,first.skillId()).versions()).hasSize(2);
    }
    @Test void changedRepositoryAndPendingReviewCannotQueueAnUpgrade()throws Exception{
        var first=publish();assertThatThrownBy(()->service.assertLinkedUpgrade(alice,first.skillId(),first.revision(),"https://github.com/other/skills/tree/main/skills/fixture-reader")).hasMessageContaining("同一仓库");
        String next=upgradedPackage(first,"b".repeat(40),"\nRecheck sources.");var updated=service.createLinked(alice,next,"INSPECTOR");updated=service.evaluate(alice,updated.skillId(),updated.revision());updated=service.submit(alice,updated.skillId(),updated.revision());
        int revision=updated.revision();assertThatThrownBy(()->service.assertLinkedUpgrade(alice,first.skillId(),revision,"https://github.com/fixtures/skills/tree/main/skills/fixture-reader")).hasMessageContaining("冻结");
        assertThat(service.get(alice,first.skillId()).activeVersion()).isEqualTo(1);
    }
    @Test void identicalCommitDoesNotCreateDuplicateVersionAndForeignUpgradeIsDenied()throws Exception{
        var first=publish();String next=upgradedPackage(first,"a".repeat(40),"");var same=service.createLinked(alice,next,"INSPECTOR");assertThat(same.latestVersion()).isEqualTo(1);assertThat(same.revision()).isEqualTo(first.revision());
        assertThat(jdbc.queryForObject("SELECT status FROM agent_skill_download WHERE download_id=?",String.class,next)).isEqualTo("NO_CHANGE");
        assertThatThrownBy(()->service.linkedUpgradeRole(bob,first.skillId())).hasMessageContaining("本人");
    }
    @Test void concurrentRevisionChangeRejectsDownloadedUpgradeWithoutChangingActiveVersion()throws Exception{
        var first=publish();String next=upgradedPackage(first,"b".repeat(40),"\nRecheck sources.");
        var archived=service.uninstallLinked(alice,first.skillId(),new SkillDtos.Command(first.revision(),"升级下载期间先卸载"));
        assertThatThrownBy(()->service.createLinked(alice,next,"INSPECTOR")).hasMessageContaining("已变化");
        var after=service.get(alice,first.skillId());assertThat(after.latestVersion()).isEqualTo(1);assertThat(after.revision()).isEqualTo(archived.revision());assertThat(after.activeVersion()).isNull();
    }
    SkillLinkService links(){return new SkillLinkService(jdbc,manager,users,storage,service,json,"unused-python",workspace.resolve("unused-installer").toString());}
    @Test void quotaRejectsBeforeSchedulingOrInsertingAnotherDownload(){
        var links=links();try{long used=storage.usage(1).bytes();org.springframework.test.util.ReflectionTestUtils.setField(links,"quotaBytes",used+5242880L-1);
            assertThatThrownBy(()->links.start(alice,new SkillLinkService.Request("https://github.com/fixtures/skills/tree/main/skills/fixture-reader","INSPECTOR","quota-request",true))).isInstanceOf(org.springframework.web.server.ResponseStatusException.class).hasMessageContaining("配额不足");
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_skill_download",Long.class)).isEqualTo(1);
        }finally{links.close();}
    }
    @Test void cleanupDeletesOnlyUnreferencedPackageRetainsOldPublishedFilesAndIsIdempotent()throws Exception{
        var first=publish();String duplicate=upgradedPackage(first,"a".repeat(40),"");service.createLinked(alice,duplicate,"INSPECTOR");var links=links();
        try{long before=links.storage(alice).usedBytes();var request=new SkillLinkService.CleanupRequest("cleanup-request",true);
            var result=links.cleanup(alice,duplicate,request);assertThat(result.get("status")).isEqualTo("COMPLETED");assertThat(((Number)result.get("removed_files")).intValue()).isEqualTo(2);
            assertThat(Files.exists(storage.directory(1,duplicate))).isFalse();assertThat(Files.exists(storage.directory(1,downloadId).resolve("SKILL.md"))).isTrue();assertThat(service.repository(alice).getAllSkills()).hasSize(1);
            assertThat(links.storage(alice).usedBytes()).isLessThan(before);assertThat(links.cleanup(alice,duplicate,request)).isEqualTo(result);assertThat(links.cleanupAudit(alice)).hasSize(1);assertThat(links.cleanupAudit(bob)).isEmpty();
        }finally{links.close();}
    }
    @Test void referencesAndForeignOwnershipPreventPhysicalCleanup(){
        var first=publish();jdbc.update("UPDATE agent_skill_download SET status='DRAFT_CREATED' WHERE download_id=?",downloadId);var links=links();
        try{assertThatThrownBy(()->links.cleanup(alice,downloadId,new SkillLinkService.CleanupRequest("reference-request",true))).hasMessageContaining("版本引用");
            assertThatThrownBy(()->links.cleanup(bob,downloadId,new SkillLinkService.CleanupRequest("foreign-request",true))).hasMessageContaining("无权限");
            assertThat(Files.exists(storage.directory(1,downloadId).resolve("SKILL.md"))).isTrue();assertThat(links.cleanupAudit(alice)).isEmpty();
        }finally{links.close();}
    }
    @Test void cleanupIntentCanResumeAfterFilesDisappearedWithoutClaimingEarlierDeletionAmounts()throws Exception{
        var first=publish();String duplicate=upgradedPackage(first,"a".repeat(40),"");service.createLinked(alice,duplicate,"INSPECTOR");var links=links();var request=new SkillLinkService.CleanupRequest("resume-request",true);
        try{links.cleanup(alice,duplicate,request);jdbc.update("UPDATE agent_skill_download SET status='PURGING' WHERE download_id=?",duplicate);jdbc.update("UPDATE agent_skill_storage_command SET status='STARTED',removed_bytes=0,removed_files=0 WHERE request_id=?",request.requestId());
            var resumed=links.cleanup(alice,duplicate,request);assertThat(resumed.get("status")).isEqualTo("COMPLETED");assertThat(((Number)resumed.get("removed_files")).intValue()).isZero();assertThat(links.cleanupAudit(alice)).hasSize(1);
        }finally{links.close();}
    }
    @Test void disablingLinkIntegrationOmitsPreviouslyPublishedLinksFromRuntimeAndCommandDirectory(){publish();service.linkStorage(null);assertThat(service.repository(alice).getAllSkills()).isEmpty();assertThat(service.availableSkills(alice)).isEmpty();}
    @Test void nativeHarnessLoadsApprovedLinkThroughSdkWithoutGainingFilesystemOrShell()throws Exception{
        var view=publish();var skill=service.repository(alice).getAllSkills().get(0);var steps=new java.util.concurrent.atomic.AtomicInteger();
        var model=mock(io.agentscope.core.model.Model.class);when(model.getModelName()).thenReturn("scripted-link-acceptance");
        when(model.stream(anyList(),anyList(),any())).thenAnswer(inv->{
            var input=Map.<String,Object>of("skillId",skill.getSkillId(),"path","SKILL.md");
            io.agentscope.core.message.ContentBlock block=steps.getAndIncrement()==0?io.agentscope.core.message.ToolUseBlock.builder().id("link-sdk-load").name(SkillEvolutionService.LOAD).input(input).content(json.writeValueAsString(input)).build():io.agentscope.core.message.TextBlock.builder().text("已读取审核正文，脚本不执行").build();
            return reactor.core.publisher.Flux.just(io.agentscope.core.model.ChatResponse.builder().content(List.of(block)).build());
        });
        var properties=new com.ruanzhu.doorhandle.module.ai.config.AgentScopeProperties();properties.setWorkspace(workspace.toString());
        var toolkit=new com.ruanzhu.doorhandle.module.ai.tool.BusinessToolkitFactory(mock(com.ruanzhu.doorhandle.contracts.agent.DetectionAgentReadApi.class),mock(com.ruanzhu.doorhandle.contracts.agent.ResourceAgentReadApi.class),mock(com.ruanzhu.doorhandle.contracts.agent.ModelAgentReadApi.class),json);
        var factory=new com.ruanzhu.doorhandle.module.ai.agent.RoleAgentFactory(properties,toolkit,id->model,service);
        var run=mock(AgentJournal.Run.class);when(run.id()).thenReturn("link-native-runtime");
        try(var agent=(io.agentscope.harness.agent.HarnessAgent)factory.create(alice,null,new com.ruanzhu.doorhandle.module.ai.journal.AgentJournalMiddleware(run,alice))){
            assertThat(agent.getToolkit().getToolNames()).contains(SkillLinkProposalTool.NAME,SkillEvolutionService.LOAD).doesNotContain("execute_shell_command","write_file","skill_manage");
            assertThat(agent.call("读取本人审核技能").block(java.time.Duration.ofSeconds(10)).getTextContent()).contains("已读取审核正文");
        }
        assertThat(service.get(alice,view.skillId()).useCount()).isEqualTo(1);
        verify(run).event(eq("AUTHORIZATION_ALLOWED"),argThat(event->SkillEvolutionService.LOAD.equals(event.get("tool"))));
    }
}
