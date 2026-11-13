package com.ruanzhu.doorhandle.module.app.service.knowledge;

import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory.Identity;
import com.ruanzhu.doorhandle.module.app.testsupport.FeatureMySql;
import com.ruanzhu.doorhandle.module.app.testsupport.CompactMySqlFixture;
import com.ruanzhu.doorhandle.framework.semantic.*;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.springframework.context.annotation.*;
import org.springframework.jdbc.core.*;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.annotation.EnableTransactionManagement;
import javax.sql.DataSource;
import java.nio.charset.StandardCharsets;
import java.time.LocalDateTime;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import static org.assertj.core.api.Assertions.*;

@TestInstance(TestInstance.Lifecycle.PER_CLASS)
@EnabledIfSystemProperty(named="doorhandle.feature.mysql.config",matches=".+")
class QualityKnowledgeMySqlTest {
    static final Identity ALICE=new Identity(1,"alice",false),BOB=new Identity(2,"bob",false),BOSS=new Identity(3,"boss",true);
    AnnotationConfigApplicationContext context;QualityKnowledgeService service;CoordinatedJdbc jdbc;Directory directory;
    CompactMySqlFixture fixture;
    @BeforeAll void start()throws Exception{
        context=new AnnotationConfigApplicationContext();
        context.getEnvironment().getPropertySources().addFirst(new org.springframework.core.env.MapPropertySource("feature-test",Map.of("app.knowledge.enabled","true")));
        context.register(Config.class,QualityKnowledgeService.class);context.refresh();
        jdbc=context.getBean(CoordinatedJdbc.class);directory=context.getBean(Directory.class);service=context.getBean(QualityKnowledgeService.class);
        fixture=new CompactMySqlFixture(context.getBean(DataSource.class));
    }
    @AfterAll void close(){try{if(fixture!=null)fixture.close();}finally{if(context!=null)context.close();}}
    @BeforeEach void reset(){
        directory.hook=null;jdbc.afterCommandRead=null;
        jdbc.update("DELETE FROM audit_event WHERE kind='KNOWLEDGE'");
        jdbc.update("DELETE FROM workflow_instance WHERE kind='KNOWLEDGE_COMMAND'");
        // Keep the real publication/revision foreign keys enabled during every reset.
        jdbc.update("UPDATE content_asset SET current_version=NULL,published_version=NULL WHERE asset_kind='KNOWLEDGE'");
        jdbc.update("DELETE c FROM content_chunk c JOIN content_asset a ON a.asset_id=c.asset_id WHERE a.asset_kind='KNOWLEDGE'");
        jdbc.update("DELETE FROM content_revision WHERE asset_kind='KNOWLEDGE'");
        jdbc.update("DELETE FROM content_asset WHERE asset_kind='KNOWLEDGE'");
        jdbc.update("DELETE FROM runtime_state WHERE namespace='KNOWLEDGE' AND scope_key=''");
        jdbc.update("DELETE FROM runtime_state WHERE namespace='SEMANTIC_INDEX' AND scope_key LIKE 'KNOWLEDGE:%'");
        org.mockito.Mockito.reset(context.getBean(SemanticVectorStore.class));
        directory.roles.put(3L,true);
    }
    String key(){return UUID.randomUUID().toString();}
    Map<String,Object> create(Identity actor,String visibility,String text,String request){return service.write(actor,null,0,"门把手检验规范",visibility,"规范.md",new KnowledgeTextExtractor.Text(text,"text/md"),text.getBytes(StandardCharsets.UTF_8),request);}
    @SuppressWarnings("unchecked") Map<String,Object> document(Map<String,Object> view){return (Map<String,Object>)view.get("document");}
    String id(Map<String,Object> view){return document(view).get("document_id").toString();}
    int revision(Map<String,Object> view){return ((Number)document(view).get("revision")).intValue();}
    @Test void semanticRecallPrefiltersAndReloadsOnlyCurrentAuthorizedSqlContent(){
        var own=create(ALICE,"PRIVATE","真实正文不是远端返回的文字",key());String id=id(own);
        var vectors=context.getBean(SemanticVectorStore.class);var index=context.getBean(KnowledgeSemanticIndex.class);
        org.mockito.Mockito.when(vectors.contains(org.mockito.ArgumentMatchers.anyString(),org.mockito.ArgumentMatchers.anyList())).thenReturn(true);
        index.reconcile();
        var valid=new SemanticVectorStore.Hit(id+"@v1:1:0",.99,"真实正文不是远端返回的文字",Map.of("source_id",id,"version","1","ordinal","1","source_sha256",QualityKnowledgeService.sha("真实正文不是远端返回的文字")));
        org.mockito.Mockito.when(vectors.search(org.mockito.ArgumentMatchers.anyString(),org.mockito.ArgumentMatchers.anyString(),org.mockito.ArgumentMatchers.any(),org.mockito.ArgumentMatchers.anyInt(),org.mockito.ArgumentMatchers.any())).thenReturn(List.of(valid));
        var hits=service.search(ALICE,"语义检索词");assertThat(hits).hasSize(1);assertThat(hits.get(0).get("content_text")).isEqualTo("真实正文不是远端返回的文字");assertThat(hits.get(0).get("retrieval_mode")).isEqualTo("SEMANTIC");
        assertThat(service.search(BOB,"语义检索词")).isEmpty();
        org.mockito.Mockito.when(vectors.search(org.mockito.ArgumentMatchers.anyString(),org.mockito.ArgumentMatchers.anyString(),org.mockito.ArgumentMatchers.any(),org.mockito.ArgumentMatchers.anyInt(),org.mockito.ArgumentMatchers.any())).thenReturn(List.of(new SemanticVectorStore.Hit(valid.id(),.99,"FORGED_REMOTE_CONTENT",valid.metadata())));
        assertThat(service.search(ALICE,"语义检索词")).isEmpty();
        org.mockito.Mockito.when(vectors.search(org.mockito.ArgumentMatchers.anyString(),org.mockito.ArgumentMatchers.anyString(),org.mockito.ArgumentMatchers.any(),org.mockito.ArgumentMatchers.anyInt(),org.mockito.ArgumentMatchers.any())).thenReturn(List.of(valid));
        var filter=org.mockito.ArgumentCaptor.forClass(SemanticVectorStore.Filter.class);
        org.mockito.Mockito.verify(vectors,org.mockito.Mockito.atLeastOnce()).search(org.mockito.ArgumentMatchers.anyString(),org.mockito.ArgumentMatchers.eq("语义检索词"),filter.capture(),org.mockito.ArgumentMatchers.anyInt(),org.mockito.ArgumentMatchers.any());
        assertThat(filter.getAllValues()).allSatisfy(value->{assertThat(value.all()).containsEntry("kind","KNOWLEDGE");assertThat(value.any()).anySatisfy(scope->assertThat(scope).containsEntry("visibility","ENTERPRISE"));});
        service.archive(ALICE,id,revision(own),true,key());assertThat(service.search(ALICE,"语义检索词")).isEmpty();
    }
    @Test void sourceIndexCasDoesNotCompleteANewerVersionAndSqlChunkReadyStaysSeparate(){
        var own=create(ALICE,"PRIVATE","原有文字段落",key());String id=id(own);var states=context.getBean(JdbcSemanticIndexState.class);var properties=context.getBean(SemanticProperties.class);var index=context.getBean(KnowledgeSemanticIndex.class);
        var first=new JdbcSemanticIndexState.Source("KNOWLEDGE",ALICE.userId(),id,1,QualityKnowledgeService.sha("原有文字段落"),"PRIVATE");
        var ticket=states.claim(first,properties.getKnowledgeCollection(),index::currentSource);
        var replacement=states.claim(first,properties.getKnowledgeCollection(),index::currentSource);
        assertThatThrownBy(()->states.finish(ticket,true,index::currentSource)).isInstanceOf(SemanticUnavailableException.class).hasMessage("VECTOR_INDEX_COMPLETION_CHANGED");
        states.finish(replacement,true,index::currentSource);var ready=states.claim(first,properties.getKnowledgeCollection(),index::currentSource);assertThat(ready.ready()).isTrue();
        service.write(ALICE,id,revision(own),"门把手检验规范","PRIVATE","规范.md",new KnowledgeTextExtractor.Text("下一版本","text/md"),"下一版本".getBytes(StandardCharsets.UTF_8),key());
        var next=new JdbcSemanticIndexState.Source("KNOWLEDGE",ALICE.userId(),id,2,QualityKnowledgeService.sha("下一版本"),"PRIVATE");
        states.claim(next,properties.getKnowledgeCollection(),index::currentSource);
        var before=jdbc.queryForMap("SELECT revision,current_ref,state_code,payload_json FROM runtime_state WHERE namespace='SEMANTIC_INDEX' AND owner_id=? AND scope_key=?",ALICE.userId(),first.key());
        assertThatThrownBy(()->states.claim(first,properties.getKnowledgeCollection(),index::currentSource)).hasMessage("VECTOR_INDEX_SOURCE_CHANGED");
        assertThatThrownBy(()->states.finish(ready,true,index::currentSource)).hasMessage("VECTOR_INDEX_SOURCE_CHANGED");
        assertThatThrownBy(()->states.confirm(ready,index::currentSource)).hasMessage("VECTOR_INDEX_SOURCE_CHANGED");
        assertThat(jdbc.queryForMap("SELECT revision,current_ref,state_code,payload_json FROM runtime_state WHERE namespace='SEMANTIC_INDEX' AND owner_id=? AND scope_key=?",ALICE.userId(),first.key())).isEqualTo(before);
        assertThat(states.state(first,properties.getKnowledgeCollection(),index::currentSource)).isEqualTo("INACTIVE");
        assertThat(jdbc.queryForObject("SELECT index_state FROM content_revision WHERE asset_id=? AND version=1",String.class,id)).isEqualTo("READY");
        assertThatThrownBy(()->jdbc.update("UPDATE runtime_state SET credential_sha256=? WHERE namespace='SEMANTIC_INDEX' AND owner_id=? AND scope_key=?","a".repeat(64),ALICE.userId(),first.key())).isInstanceOf(org.springframework.dao.DataAccessException.class);
    }
    @Test void activeRevisionWithNoCanonicalChunksNeverBecomesVectorReady(){
        var own=create(ALICE,"PRIVATE","待核对文字段落",key());String id=id(own);var index=context.getBean(KnowledgeSemanticIndex.class);var vectors=context.getBean(SemanticVectorStore.class);
        jdbc.update("DELETE FROM content_chunk WHERE asset_id=? AND version=1",id);
        jdbc.update("UPDATE content_revision SET chunk_count=0,index_state='EMPTY' WHERE asset_id=? AND version=1",id);
        index.reconcile();
        assertThat(index.state(ALICE.userId(),id,1,QualityKnowledgeService.sha("待核对文字段落"),"PRIVATE")).isEqualTo("FAILED");
        org.mockito.Mockito.verify(vectors,org.mockito.Mockito.never()).upsert(org.mockito.ArgumentMatchers.anyString(),org.mockito.ArgumentMatchers.anyList(),org.mockito.ArgumentMatchers.any());
        assertThat(jdbc.queryForObject("SELECT index_state FROM content_revision WHERE asset_id=? AND version=1",String.class,id)).isEqualTo("EMPTY");
    }
    @Test void publicationDuringEmbeddingDoesNotHoldSqlLocksOrCompleteAnOldSource()throws Exception{
        var own=create(ALICE,"PRIVATE","旧版检验步骤",key());String id=id(own);var index=context.getBean(KnowledgeSemanticIndex.class);var vectors=context.getBean(SemanticVectorStore.class);var pool=Executors.newSingleThreadExecutor();
        org.mockito.Mockito.when(vectors.contains(org.mockito.ArgumentMatchers.anyString(),org.mockito.ArgumentMatchers.anyList())).thenReturn(false);
        org.mockito.Mockito.doAnswer(call->{
            assertThat(org.springframework.transaction.support.TransactionSynchronizationManager.isActualTransactionActive()).as("provider call must not hold the source SQL transaction").isFalse();
            pool.submit(()->service.write(ALICE,id,revision(own),"门把手检验规范","PRIVATE","规范.md",new KnowledgeTextExtractor.Text("新版检验步骤","text/md"),"新版检验步骤".getBytes(StandardCharsets.UTF_8),key())).get(5,TimeUnit.SECONDS);return null;
        }).when(vectors).upsert(org.mockito.ArgumentMatchers.anyString(),org.mockito.ArgumentMatchers.anyList(),org.mockito.ArgumentMatchers.any());
        try{index.reconcile();}finally{pool.shutdownNow();}
        assertThat(((Number)document(service.revision(ALICE,id,null)).get("current_version")).intValue()).isEqualTo(2);
        assertThat(index.state(ALICE.userId(),id,2,QualityKnowledgeService.sha("新版检验步骤"),"PRIVATE")).isEqualTo("PENDING");
        assertThat(jdbc.queryForObject("SELECT state_code FROM runtime_state WHERE namespace='SEMANTIC_INDEX' AND owner_id=? AND scope_key=?",String.class,ALICE.userId(),"KNOWLEDGE:"+id)).isNotEqualTo("READY");
    }
    @Test void archivalDuringEmbeddingPreventsReadyCompletionAndMakesTheSourceInactive()throws Exception{
        var own=create(ALICE,"PRIVATE","需要归档的检验步骤",key());String id=id(own);var index=context.getBean(KnowledgeSemanticIndex.class);var vectors=context.getBean(SemanticVectorStore.class);var pool=Executors.newSingleThreadExecutor();
        org.mockito.Mockito.when(vectors.contains(org.mockito.ArgumentMatchers.anyString(),org.mockito.ArgumentMatchers.anyList())).thenReturn(false);
        org.mockito.Mockito.doAnswer(call->{
            assertThat(org.springframework.transaction.support.TransactionSynchronizationManager.isActualTransactionActive()).isFalse();
            pool.submit(()->service.archive(ALICE,id,revision(own),true,key())).get(5,TimeUnit.SECONDS);return null;
        }).when(vectors).upsert(org.mockito.ArgumentMatchers.anyString(),org.mockito.ArgumentMatchers.anyList(),org.mockito.ArgumentMatchers.any());
        try{index.reconcile();}finally{pool.shutdownNow();}
        assertThat(index.state(ALICE.userId(),id,1,QualityKnowledgeService.sha("需要归档的检验步骤"),"PRIVATE")).isEqualTo("INACTIVE");
        assertThat(jdbc.queryForObject("SELECT state_code FROM runtime_state WHERE namespace='SEMANTIC_INDEX' AND owner_id=? AND scope_key=?",String.class,ALICE.userId(),"KNOWLEDGE:"+id)).isEqualTo("PENDING");
    }
    @Test void privateMaterialCannotBeReadSearchedOrDownloadedByOtherEmployeeOrSupervisor(){var saved=create(ALICE,"PRIVATE","锈蚀门把手需要检查涂层和机械连接","private-material");assertThat(service.search(ALICE,"锈蚀")).hasSize(1);for(var actor:List.of(BOB,BOSS)){assertThat(service.search(actor,"锈蚀")).isEmpty();assertThatThrownBy(()->service.revision(actor,id(saved),1)).isInstanceOf(BusinessException.class);assertThatThrownBy(()->service.source(actor,id(saved),1)).isInstanceOf(BusinessException.class);}assertThat(service.source(ALICE,id(saved),1).bytes()).isEqualTo("锈蚀门把手需要检查涂层和机械连接".getBytes(StandardCharsets.UTF_8));}
    @Test void roleCannotBeForgedAndEnterpriseVisibilityIsRefreshed(){assertThatThrownBy(()->create(new Identity(1,"alice",true),"ENTERPRISE","检验规范正文","forged-supervisor")).isInstanceOf(BusinessException.class);var saved=create(BOSS,"ENTERPRISE","门把手涂层损伤需要复核","enterprise-material");assertThat(service.search(ALICE,"涂层")).hasSize(1);service.archive(BOSS,id(saved),revision(saved),true,key());assertThat(service.search(ALICE,"涂层")).isEmpty();assertThatThrownBy(()->service.source(ALICE,id(saved),1)).isInstanceOf(BusinessException.class);}
    @Test void versionsKeepOriginalBytesAndLifecycleUsesIndependentOptimisticRevision(){var first=create(ALICE,"PRIVATE","第一版缺陷说明","version-original");var archived=service.archive(ALICE,id(first),revision(first),true,key());assertThatThrownBy(()->service.archive(ALICE,id(first),revision(first),false,key())).isInstanceOf(BusinessException.class);var restored=service.archive(ALICE,id(first),revision(archived),false,key());var second=service.write(ALICE,id(first),revision(restored),"修订规范","PRIVATE","新版.txt",new KnowledgeTextExtractor.Text("第二版检验说明","text/txt"),"第二版检验说明".getBytes(StandardCharsets.UTF_8),key());assertThat(document(second).get("current_version")).isEqualTo(2);assertThat(service.source(ALICE,id(first),1).bytes()).isEqualTo("第一版缺陷说明".getBytes(StandardCharsets.UTF_8));assertThat(service.revision(ALICE,id(first),1).get("revision")).asString().contains("title=门把手检验规范","filename=规范.md");}
    @Test void repeatedRequestHasOneIndexAndConflictingPayloadCannotReuseTheKey(){var first=create(ALICE,"PRIVATE","检查门把手锈蚀和变形","same-request-id");var again=create(ALICE,"PRIVATE","检查门把手锈蚀和变形","same-request-id");assertThat(id(again)).isEqualTo(id(first));assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM content_asset WHERE asset_kind='KNOWLEDGE'",Long.class)).isEqualTo(1);assertThatThrownBy(()->create(ALICE,"PRIVATE","不同检验资料","same-request-id")).isInstanceOf(BusinessException.class);}
    @Test void auditFailureRollsBackDocumentRevisionIndexAndCommand(){jdbc.execute("ALTER TABLE audit_event ADD CONSTRAINT reject_knowledge_audit CHECK(kind<>'KNOWLEDGE' OR action<>'INDEX')");try{assertThatThrownBy(()->create(ALICE,"PRIVATE","审计失败不应留下资料",key())).isInstanceOf(org.springframework.dao.DataAccessException.class).hasMessageContaining("reject_knowledge_audit");assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM content_asset WHERE asset_kind='KNOWLEDGE'",Long.class)).isZero();assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM content_revision WHERE asset_kind='KNOWLEDGE'",Long.class)).isZero();assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM content_chunk",Long.class)).isZero();assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM workflow_instance WHERE kind='KNOWLEDGE_COMMAND'",Long.class)).isZero();}finally{jdbc.execute("ALTER TABLE audit_event DROP CHECK reject_knowledge_audit");}}
    @Test void textAndOriginalCorruptionAreRejectedAndStoredTimeKeepsWallClock(){var first=create(ALICE,"PRIVATE","原始检验资料说明",key());jdbc.update("UPDATE content_asset SET updated_at='2026-10-27 01:02:03' WHERE asset_kind='KNOWLEDGE' AND asset_id=?",id(first));@SuppressWarnings("unchecked")var rows=(List<Map<String,Object>>)service.list(ALICE,1,20,"").get("records");assertThat(rows.get(0).get("updated_at")).isEqualTo(LocalDateTime.of(2026,10,27,1,2,3));jdbc.update("UPDATE content_revision SET source_bytes=? WHERE asset_kind='KNOWLEDGE' AND asset_id=?","tampered".getBytes(StandardCharsets.UTF_8),id(first));assertThatThrownBy(()->service.source(ALICE,id(first),1)).hasMessageContaining("摘要");jdbc.update("UPDATE content_revision SET content_text='tampered' WHERE asset_kind='KNOWLEDGE' AND asset_id=?",id(first));assertThatThrownBy(()->service.revision(ALICE,id(first),1)).hasMessageContaining("摘要");}
    @Test void unicodeChunksAndCitationLinksRemainBoundToCurrentReadableVersion(){String text="检验说明".repeat(248)+"𠀀"+"缺陷复核".repeat(100);var first=create(ALICE,"PRIVATE",text,key());assertThat(service.context(ALICE,"缺陷复核")).contains(id(first)+"@v1:","/#/quality/knowledge?documentId=");assertThat(service.context(BOB,"缺陷复核")).isEmpty();@SuppressWarnings("unchecked")var chunks=(List<Map<String,Object>>)first.get("chunks");for(var row:chunks)assertThat(row.get("content_text").toString().getBytes(StandardCharsets.UTF_8)).doesNotContain((byte)0x3f);}
    @Test void concurrentRetryReturnsSameCommittedDocumentWithoutDuplicateVersions()throws Exception{var firstHeld=new CountDownLatch(1);var releaseFirst=new CountDownLatch(1);var secondRead=new CountDownLatch(1);var count=new AtomicInteger();directory.hook=()->{if(Thread.currentThread().getName().equals("knowledge-first")&&count.incrementAndGet()==2){firstHeld.countDown();await(releaseFirst);}};jdbc.afterCommandRead=()->{if(Thread.currentThread().getName().equals("knowledge-second"))secondRead.countDown();};var pool=Executors.newFixedThreadPool(2);try{var first=pool.submit(()->{Thread.currentThread().setName("knowledge-first");return create(ALICE,"PRIVATE","相同请求只保存一个资料版本","concurrent-retry");});assertThat(firstHeld.await(5,TimeUnit.SECONDS)).isTrue();var second=pool.submit(()->{Thread.currentThread().setName("knowledge-second");return create(ALICE,"PRIVATE","相同请求只保存一个资料版本","concurrent-retry");});assertThat(secondRead.await(5,TimeUnit.SECONDS)).isTrue();releaseFirst.countDown();assertThat(id(first.get(8,TimeUnit.SECONDS))).isEqualTo(id(second.get(8,TimeUnit.SECONDS)));assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM content_asset WHERE asset_kind='KNOWLEDGE'",Long.class)).isEqualTo(1);assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM content_revision WHERE asset_kind='KNOWLEDGE'",Long.class)).isEqualTo(1);}finally{releaseFirst.countDown();pool.shutdownNow();directory.hook=null;jdbc.afterCommandRead=null;}}
    @Test void httpMultipartAndVersionedDeliveryUseRealServiceAndKeepRequiredActionMarker()throws Exception{
        var trusted=org.mockito.Mockito.mock(BusinessUserDirectory.class);org.mockito.Mockito.when(trusted.authenticated()).thenReturn(ALICE);
        var controller=new com.ruanzhu.doorhandle.module.app.controller.QualityKnowledgeController(service,new KnowledgeTextExtractor(),trusted);
        var http=org.springframework.test.web.servlet.setup.MockMvcBuilders.standaloneSetup(controller).setControllerAdvice(new com.ruanzhu.doorhandle.common.GlobalExceptionHandler()).build();
        byte[] original="门把手涂层须人工复核".getBytes(StandardCharsets.UTF_8);
        var file=new org.springframework.mock.web.MockMultipartFile("file","C:\\incoming\\检验规范.txt","text/plain",original);
        http.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders.multipart("/api/quality/knowledge").file(file).param("title","检验规范").param("requestId","http-multipart-key")).andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath("$.code").value(400));
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM content_asset WHERE asset_kind='KNOWLEDGE'",Long.class)).isZero();
        var response=http.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders.multipart("/api/quality/knowledge").file(file).param("title","检验规范").param("requestId","http-multipart-key").header("X-Knowledge-Action","update")).andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath("$.code").value(200)).andReturn();
        String id=new com.fasterxml.jackson.databind.ObjectMapper().readTree(response.getResponse().getContentAsByteArray()).at("/data/document/document_id").asText();
        var download=http.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get("/api/quality/knowledge/"+id+"/versions/1/source")).andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.status().isOk()).andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.header().string("Cache-Control","no-store")).andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.header().string("X-Content-Type-Options","nosniff")).andReturn().getResponse();
        assertThat(download.getContentAsByteArray()).isEqualTo(original);assertThat(download.getHeader("X-Content-SHA256")).isEqualTo(QualityKnowledgeService.sha(new String(original,StandardCharsets.UTF_8)));
        assertThat(service.source(ALICE,id,1).filename()).isEqualTo("检验规范.txt");
    }
    static void await(CountDownLatch latch){try{if(!latch.await(6,TimeUnit.SECONDS))throw new IllegalStateException("Barrier timed out");}catch(InterruptedException error){Thread.currentThread().interrupt();throw new IllegalStateException(error);}}
    static class Directory implements BusinessUserDirectory {final Map<Long,Boolean> roles=new ConcurrentHashMap<>(Map.of(1L,false,2L,false,3L,true));volatile Runnable hook;public Identity current(long id,String name){if(hook!=null)hook.run();return new Identity(id,name,roles.getOrDefault(id,false));}public Identity lockCurrent(long id,String name){return current(id,name);}}
    static class CoordinatedJdbc extends JdbcTemplate {volatile Runnable afterCommandRead;CoordinatedJdbc(DataSource source){super(source);}@Override public <T>List<T> query(String sql,RowMapper<T> mapper,Object...args){var result=super.query(sql,mapper,args);if(sql.startsWith("SELECT * FROM workflow_instance WHERE kind=? AND idempotency_scope=?")&&args.length>0&&"KNOWLEDGE_COMMAND".equals(args[0])&&afterCommandRead!=null)afterCommandRead.run();return result;}}
    @Configuration @EnableTransactionManagement static class Config {
        @Bean DataSource source(){return FeatureMySql.source();}@Bean CoordinatedJdbc jdbc(DataSource source){return new CoordinatedJdbc(source);}@Bean DataSourceTransactionManager transactions(DataSource source){return new DataSourceTransactionManager(source);}@Bean Directory users(){return new Directory();}
        @Bean ObjectMapper json(){return new ObjectMapper();}
        @Bean SemanticProperties semanticProperties(){return new SemanticProperties();}
        @Bean SemanticVectorStore semanticVectors(){return org.mockito.Mockito.mock(SemanticVectorStore.class);}
        @Bean JdbcSemanticIndexState semanticStates(JdbcTemplate jdbc,ObjectMapper json,SemanticProperties properties){return new JdbcSemanticIndexState(jdbc,json,properties);}
        @Bean KnowledgeSemanticIndex semanticIndex(JdbcTemplate jdbc,SemanticVectorStore vectors,SemanticProperties properties,JdbcSemanticIndexState states){return new KnowledgeSemanticIndex(jdbc,vectors,properties,states);}
    }
}
