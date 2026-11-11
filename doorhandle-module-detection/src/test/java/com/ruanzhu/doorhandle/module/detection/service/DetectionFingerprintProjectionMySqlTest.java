package com.ruanzhu.doorhandle.module.detection.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionImageFingerprintMapper;
import com.ruanzhu.doorhandle.module.detection.support.CompactDetectionMySqlFixture;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.springframework.dao.DataAccessException;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.jdbc.core.JdbcTemplate;

import java.sql.SQLException;
import java.util.List;

import static org.assertj.core.api.Assertions.*;
import static com.ruanzhu.doorhandle.module.detection.EcsIsolatedMysql.assertCheckViolation;

@EnabledIfSystemProperty(named="doorhandle.fingerprint.mysql.config",matches=".+")
class DetectionFingerprintProjectionMySqlTest {
    CompactDetectionMySqlFixture fixture;
    JdbcTemplate jdbc;
    DetectionImageFingerprintMapper fingerprints;
    final String hash="abcdef0123456789".repeat(4);

    @BeforeEach void seed() throws Exception {
        fixture=new CompactDetectionMySqlFixture("doorhandle.fingerprint.mysql.config");
        jdbc=new JdbcTemplate(fixture.source());
        fingerprints=new DetectionImageFingerprintMapper(jdbc,new ObjectMapper());
        jdbc.update("INSERT INTO content_asset(asset_id,asset_kind,identity_key,title,filename,visibility,lifecycle,current_version,created_at,updated_at) VALUES('fingerprint-777','DETECTION_IMAGE',?,'photo','photo.jpg','SYSTEM','PREPARING',NULL,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))",hash);
        jdbc.update("INSERT INTO content_revision(asset_id,asset_kind,version,filename,content_sha256,object_key,created_at) VALUES('fingerprint-777','DETECTION_IMAGE',1,'photo.jpg',?,'old/original.jpg',UTC_TIMESTAMP(6))",hash);
        jdbc.update("UPDATE content_asset SET current_version=1,lifecycle='ACTIVE' WHERE asset_id='fingerprint-777'");
        jdbc.update("INSERT INTO runtime_state(namespace,owner_id,scope_key,revision,state_code,current_ref,payload_version,payload_json,created_at) VALUES('DETECTION_FINGERPRINT',0,?,17,'DETECTED','old-task',1,?,UTC_TIMESTAMP(6))",hash,"{\"originalId\":777,\"sourceOwnerKey\":\"staff-X\"}");
    }
    @AfterEach void close() {
        if(fixture!=null)fixture.close();
    }
    @Test void originalIdentityAndOwnerArePreservedWithoutBecomingContentIdentity() {
        var value=fingerprints.findBySha256(List.of(hash.toUpperCase(java.util.Locale.ROOT))).get(0);
        assertThat(value.getId()).isEqualTo(777L);assertThat(value.getOwnerUserId()).isEqualTo("staff-X");
        assertThat(value.getVersion()).isEqualTo(17);assertThat(value.getLastTaskId()).isEqualTo("old-task");
        assertThat(value.getObjectKey()).isEqualTo("old/original.jpg");assertThat(fingerprints.findBySha256(List.of())).isEmpty();
    }
    @Test void malformedSourceOwnerCannotBecomeAnAccountId() {
        assertCheckViolation(()->jdbc.update("UPDATE runtime_state SET payload_json=? WHERE namespace='DETECTION_FINGERPRINT'","{\"originalId\":777,\"sourceOwnerKey\":12}"), "ck_runtime_fingerprint");
        assertThat(fingerprints.findBySha256(List.of(hash)).get(0).getOwnerUserId()).isEqualTo("staff-X");
    }
    @Test void missingContentVersionFailsInsteadOfSilentlyReportingNewImage() {
        jdbc.update("UPDATE content_asset SET current_version=NULL WHERE asset_id='fingerprint-777'");
        assertThatThrownBy(()->fingerprints.findBySha256(List.of(hash)))
                .isInstanceOf(IllegalStateException.class).hasMessage("图片指纹投影或内容引用不完整");
    }
    @Test void missingRevisionReferenceIsRejectedWithoutChangingCurrentFingerprint() {
        var original=fingerprints.findBySha256(List.of(hash));
        assertThatThrownBy(()->jdbc.update("UPDATE content_asset SET current_version=2 WHERE asset_id='fingerprint-777'"))
                .isInstanceOf(DataIntegrityViolationException.class)
                .satisfies(failure->{
                    var cause=((DataAccessException)failure).getMostSpecificCause();
                    assertThat(cause).isInstanceOf(SQLException.class);
                    var sql=(SQLException)cause;
                    assertThat(sql.getErrorCode()).isEqualTo(1452);
                    assertThat(sql.getSQLState()).isEqualTo("23000");
                    assertThat(sql.getMessage()).contains("fk_content_current_revision");
                });
        assertThat(jdbc.queryForObject("SELECT current_version FROM content_asset WHERE asset_id='fingerprint-777'",Integer.class))
                .isEqualTo(1);
        assertThat(fingerprints.findBySha256(List.of(hash))).usingRecursiveComparison().isEqualTo(original);
    }
    @Test void anUnrelatedContentKindCannotSupplyTheFingerprintFile() {
        jdbc.update("INSERT INTO content_asset(asset_id,asset_kind,owner_user_id,identity_key,title,filename,visibility,created_at,updated_at) VALUES('unrelated','WORKSPACE_FILE',1,?,'other','other.jpg','PRIVATE',UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))",hash);
        assertThat(fingerprints.findBySha256(List.of(hash))).hasSize(1);
    }
    @Test void aKnownFingerprintClockCannotBeErasedByClaimingImportProvenance() {
        assertCheckViolation(()->jdbc.update("UPDATE content_revision SET legacy_source='detection_image_fingerprint',legacy_id=777,created_at=NULL WHERE asset_id='fingerprint-777'"), "ck_legacy_content_revision_created_at");
    }
}
