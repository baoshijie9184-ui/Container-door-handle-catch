package com.ruanzhu.doorhandle.module.system.config;

import com.ruanzhu.doorhandle.contracts.security.QualityAssigneeDirectory;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.http.converter.json.Jackson2ObjectMapperBuilder;
import static org.assertj.core.api.Assertions.*;

class CollaborationJsonConfigurationTest {
    @ParameterizedTest @ValueSource(longs={1L,9007199254740993L,Long.MAX_VALUE})
    void serializesAssigneeIdsExactlyWithoutChangingTheDomainType(long id)throws Exception{
        var builder=Jackson2ObjectMapperBuilder.json();new CollaborationJsonConfiguration().collaborationIdentityJson().customize(builder);
        var json=builder.build();var option=new QualityAssigneeDirectory.Option("inspector",id,"revision");
        var output=json.readTree(json.writeValueAsBytes(option));assertThat(output.path("userId").isTextual()).isTrue();
        assertThat(output.path("userId").textValue()).isEqualTo(Long.toString(id));assertThat(option.userId()).isEqualTo(id);
    }
}
