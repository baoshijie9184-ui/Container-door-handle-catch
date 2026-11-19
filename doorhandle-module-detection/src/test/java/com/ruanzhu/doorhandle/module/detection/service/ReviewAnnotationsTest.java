package com.ruanzhu.doorhandle.module.detection.service;

import com.ruanzhu.doorhandle.common.BusinessException;
import org.junit.jupiter.api.Test;
import java.util.List;
import static org.junit.jupiter.api.Assertions.*;

class ReviewAnnotationsTest {
    final ReviewAnnotations.Target normal=new ReviewAnnotations.Target("Normal",List.of(0.,1.,30.5,40.));
    final ReviewAnnotations.Model model=new ReviewAnnotations.Model("basis",80,60,List.of(normal));
    @Test void allowsSixCategoriesAndFullImageEdges() {
        for(String label:List.of("Normal","Bent","Deformed","Rusty","Missing","Compromised"))
            assertDoesNotThrow(()->ReviewAnnotations.validate(List.of(new ReviewAnnotations.Target(label,List.of(0.,0.,80.,60.))), model));
    }
    @Test void rejectsMalformedOrOffImageAndWrongTargetCount() {
        assertThrows(BusinessException.class,()->ReviewAnnotations.validate(List.of(),model));
        assertThrows(BusinessException.class,()->ReviewAnnotations.validate(List.of(new ReviewAnnotations.Target("维修",normal.box())),model));
        for(var box:List.of(List.of(-1.,1.,2.,2.),List.of(5.,1.,5.,2.),List.of(0.,1.,2.,61.),List.of(0.,Double.NaN,2.,2.)))
            assertThrows(BusinessException.class,()->ReviewAnnotations.validate(List.of(new ReviewAnnotations.Target("Bent",box)),model));
    }
}
