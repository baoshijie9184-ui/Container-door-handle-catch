package com.ruanzhu.doorhandle.common;

import java.sql.*;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.*;

/** Preserve DATETIME wall-clock fields instead of applying the JVM's default time zone. */
public final class LocalDateTimeRow {
    private LocalDateTimeRow() { }
    public static Map<String,Object> read(ResultSet result,int index)throws SQLException {
        var metadata=result.getMetaData();var row=new LinkedHashMap<String,Object>();
        for(int column=1;column<=metadata.getColumnCount();column++) {
            Object value=switch(metadata.getColumnType(column)) {
                case Types.TIMESTAMP -> result.getObject(column,LocalDateTime.class);
                case Types.DATE -> result.getObject(column,LocalDate.class);
                case Types.BLOB,Types.BINARY,Types.VARBINARY,Types.LONGVARBINARY -> result.getBytes(column);
                case Types.CLOB,Types.NCLOB -> result.getString(column);
                default -> result.getObject(column);
            };
            row.put(metadata.getColumnLabel(column),value);
        }
        return row;
    }
}
