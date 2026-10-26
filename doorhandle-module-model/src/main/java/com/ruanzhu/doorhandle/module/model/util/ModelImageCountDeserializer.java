package com.ruanzhu.doorhandle.module.model.util;

import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.core.JsonToken;
import com.fasterxml.jackson.databind.DeserializationContext;
import com.fasterxml.jackson.databind.JsonDeserializer;
import com.fasterxml.jackson.databind.JsonMappingException;
import java.io.IOException;

/** Image counts must never be silently truncated from fractional JSON numbers. */
public final class ModelImageCountDeserializer extends JsonDeserializer<Integer> {
    @Override
    public Integer deserialize(JsonParser parser, DeserializationContext context) throws IOException {
        if (!parser.hasToken(JsonToken.VALUE_NUMBER_INT))
            throw JsonMappingException.from(parser, "图片数量必须为整数，未知请使用 null 或省略字段");
        return parser.getIntValue();
    }
}
