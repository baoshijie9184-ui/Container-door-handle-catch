package com.ruanzhu.doorhandle.module.system.mapper;
import com.ruanzhu.doorhandle.module.system.entity.AccountEmployeeBinding;
import org.apache.ibatis.annotations.*;
import java.util.Collection;
import java.util.List;

/** Only association reads and the versioned field update are exposed; accounts cannot be deleted here. */
@Mapper
public interface AccountEmployeeBindingMapper {
    @Select("SELECT id,employee_id,binding_version FROM users WHERE id=#{userId}")
    @Results(id = "association", value = {
            @Result(column = "id", property = "userId", id = true),
            @Result(column = "employee_id", property = "employeeId"),
            @Result(column = "binding_version", property = "version")
    })
    AccountEmployeeBinding selectById(@Param("userId") Long userId);

    @Select("SELECT id,employee_id,binding_version FROM users WHERE id=#{userId} FOR SHARE")
    @ResultMap("association")
    AccountEmployeeBinding selectLockedById(@Param("userId") Long userId);

    @Select({"<script>", "SELECT id,employee_id,binding_version FROM users WHERE",
            "<choose><when test='userIds != null and !userIds.isEmpty()'>",
            "id IN <foreach item='userId' collection='userIds' open='(' separator=',' close=')'>#{userId}</foreach>",
            "</when><otherwise>1=0</otherwise></choose>", "</script>"})
    @ResultMap("association")
    List<AccountEmployeeBinding> selectByUserIds(@Param("userIds") Collection<Long> userIds);

    @Select("SELECT COUNT(*) FROM users WHERE employee_id=#{employeeId}")
    long countByEmployeeId(@Param("employeeId") Long employeeId);

    @Select("SELECT COUNT(*) FROM users WHERE employee_id=#{employeeId} AND id<>#{userId}")
    long countOtherAccountsForEmployee(@Param("employeeId") Long employeeId, @Param("userId") Long userId);

    /** Keep profile timestamps and credentials unchanged; association has its own revision. */
    @Update("UPDATE users SET employee_id=#{employeeId},binding_version=binding_version+1,binding_history_present=TRUE,updated_at=updated_at "
            + "WHERE id=#{userId} AND binding_version=#{expectedVersion}")
    int compareAndSet(@Param("userId") Long userId, @Param("employeeId") Long employeeId,
            @Param("expectedVersion") int expectedVersion);
}
