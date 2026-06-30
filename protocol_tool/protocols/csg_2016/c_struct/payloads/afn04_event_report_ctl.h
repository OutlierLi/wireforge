/* @wireforge di=E8020404 desc=允许/禁止上报从节点事件 */
typedef struct __attribute__((packed)) {
    uint8_t enable; /* @enum 0:禁止上报 1:允许上报 */
} afn04_event_report_ctl_t;
