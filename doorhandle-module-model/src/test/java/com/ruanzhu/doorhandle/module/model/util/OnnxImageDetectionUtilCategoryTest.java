package com.ruanzhu.doorhandle.module.model.util;

import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;

class OnnxImageDetectionUtilCategoryTest {

    @Test
    void mapsSixProbabilitiesToUpdatedCategories() {
        Map<String, Float> probabilities = OnnxImageDetectionUtil.mapProbabilitiesForTest(
                new float[]{0.1f, 0.2f, 0.3f, 0.15f, 0.05f, 0.2f}
        );

        assertEquals(6, probabilities.size());
        assertEquals(0.1f, probabilities.get("Normal"));
        assertEquals(0.2f, probabilities.get("Bent"));
        assertEquals(0.3f, probabilities.get("Deformed"));
        assertEquals(0.15f, probabilities.get("Rusty"));
        assertEquals(0.05f, probabilities.get("Missing"));
        assertEquals(0.2f, probabilities.get("Compromised"));
    }
}
