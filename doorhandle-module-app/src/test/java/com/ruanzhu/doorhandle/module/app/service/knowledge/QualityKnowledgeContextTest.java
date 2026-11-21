package com.ruanzhu.doorhandle.module.app.service.knowledge;

import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory.Identity;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.doReturn;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.spy;

class QualityKnowledgeContextTest {
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
