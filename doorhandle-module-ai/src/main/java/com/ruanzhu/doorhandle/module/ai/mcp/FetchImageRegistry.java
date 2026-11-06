package com.ruanzhu.doorhandle.module.ai.mcp;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.HttpStatus;
import java.util.Map;

/** One SQL fence per immutable image. Readers remain enforced when the cleanup UI is disabled. */
public final class FetchImageRegistry {
    private final JdbcTemplate jdbc;private final TransactionTemplate tx;private final boolean required;
    public FetchImageRegistry(JdbcTemplate jdbc,PlatformTransactionManager manager,boolean required){this.jdbc=jdbc;this.tx=new TransactionTemplate(manager);this.tx.setTimeout(10);this.required=required;}
    public boolean available(){
        Integer count=jdbc.queryForObject("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='content_asset'",Integer.class);
        if(count==null||count==0){if(required)throw new IllegalStateException("MCP_IMAGE_MIGRATION_REQUIRED");return false;}return true;
    }
    public void schema(){if(available()){jdbc.queryForList("SELECT identity_key AS image_id,lifecycle AS state,revision,connector_cleanup_request AS cleanup_request,connector_runner_pool_id AS runner_pool_id,connector_archive_sha256 AS archive_sha256,connector_image_absent AS image_absent FROM content_asset WHERE asset_kind='CONNECTOR_IMAGE' AND (1=0) ");jdbc.queryForList("SELECT mcp_image_id AS image_id FROM workflow_instance WHERE kind='MCP_EXECUTION' AND (1=0) ");}}
    public Map<String,Object> lock(String image){
        if(image==null||!image.matches("sha256:[a-f0-9]{64}"))throw new IllegalArgumentException("MCP_IMAGE_INVALID");
        jdbc.update("INSERT IGNORE INTO content_asset(identity_key,lifecycle,asset_id,asset_kind,title,visibility,created_at,revision,connector_image_absent,updated_at) SELECT v.image_id,v.state,CONCAT('connector-image:',v.image_id),'CONNECTOR_IMAGE',v.image_id,'SYSTEM',UTC_TIMESTAMP(6),0,FALSE,UTC_TIMESTAMP(6) FROM (SELECT ? AS image_id,'ACTIVE' AS state) v",image);
        return jdbc.queryForMap("SELECT identity_key AS image_id,lifecycle AS state,revision AS revision,connector_cleanup_request AS cleanup_request,connector_cleanup_owner_user_id AS cleanup_owner_user_id,connector_runner_pool_id AS runner_pool_id,connector_archive_sha256 AS archive_sha256,connector_image_absent AS image_absent,updated_at AS updated_at FROM content_asset WHERE asset_kind='CONNECTOR_IMAGE' AND (identity_key=?) FOR UPDATE",image);
    }
    public void usable(String image){
        if(image==null)return;
        if(!available())return; // Never cache absence across a later controlled migration.
        tx.executeWithoutResult(status->{if(!"ACTIVE".equals(lock(image).get("state")))throw new ResponseStatusException(HttpStatus.CONFLICT,"此固定 Fetch 镜像已进入回收流程 不能建立新的引用或执行");});
    }
}
