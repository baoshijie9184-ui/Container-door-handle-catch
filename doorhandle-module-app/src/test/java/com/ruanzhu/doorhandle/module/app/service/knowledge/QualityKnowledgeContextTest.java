package com.ruanzhu.doorhandle.module.app.service.knowledge;

import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory.Identity;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.when;
import static org.mockito.Mockito.doReturn;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.spy;

class QualityKnowledgeContextTest {
    @Test
    void referenceRequiresCurrentVisibleDocumentAndTheSamePassage() {
        var actor = new Identity(1, "inspector", false);
        var users = mock(BusinessUserDirectory.class);
        var jdbc = mock(JdbcTemplate.class);
        var service = spy(new QualityKnowledgeService(jdbc, users));
        Map<String,Object> hit = Map.of("document_id", "doc-1", "current_version", 2, "ordinal_no", 3,
                "title", "检验规范", "locator", "第 3 段", "content_text", "沿边缘检查表面损伤。");
        doReturn(List.of(hit)).when(service).search(actor, "表面损伤");
        when(users.current(1, "inspector")).thenReturn(actor);
        doReturn(List.of(hit), List.of()).when(jdbc).query(
                contains("d.lifecycle='ACTIVE'"), org.mockito.ArgumentMatchers.<RowMapper<Map<String,Object>>>any(),
                eq("doc-1"), eq(2), eq(3), eq(1L));

        var result = service.contextReference(actor, "表面损伤", 3000);
        assertThat(result.sources()).hasSize(1);
        var source = result.sources().get(0);
        assertThat(source.kind()).isEqualTo("KNOWLEDGE");
        assertThat(source.resourceId()).isEqualTo("doc-1");
        assertThat(source.version()).matches("2:3:[a-f0-9]{64}");
        service.assertContextSource(actor, source.resourceId(), source.version());

        assertThatThrownBy(() -> service.assertContextSource(actor, source.resourceId(), source.version()))
                .isInstanceOf(SecurityException.class).hasMessageContaining("当前账号不可使用");
    }

    @Test
    void contextKeepsTheCitationIdentifierWithoutLinkingToTheRetiredPage() {
        var actor = new Identity(1, "inspector", false);
        var service = spy(new QualityKnowledgeService(mock(JdbcTemplate.class), mock(BusinessUserDirectory.class)));
        doReturn(List.of(Map.of("document_id", "doc-1", "current_version", 2, "ordinal_no", 3,
                "title", "检验规范", "locator", "第 3 段", "content_text", "沿边缘检查表面损伤。")))
                .when(service).search(actor, "表面损伤");

        assertThat(service.context(actor, "表面损伤"))
                .contains("doc-1@v2:3", "检验规范", "第 3 段", "沿边缘检查表面损伤。")
                .doesNotContain("/#/quality/knowledge");
    }
}
