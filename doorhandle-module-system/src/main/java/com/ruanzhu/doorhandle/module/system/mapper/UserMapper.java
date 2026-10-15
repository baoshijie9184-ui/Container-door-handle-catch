package com.ruanzhu.doorhandle.module.system.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.ruanzhu.doorhandle.module.system.entity.User;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface UserMapper extends BaseMapper<User> {
    @Select("SELECT username FROM users WHERE UPPER(role) IN ('INSPECTOR','OPERATOR') "
            + "AND LOCATE(#{keyword}, username) > 0 ORDER BY username LIMIT 50")
    java.util.List<String> findQualityAssignees(@Param("keyword") String keyword);

    @Select("SELECT * FROM users WHERE username = #{username}")
    User findByUsername(@Param("username") String username);
} 
