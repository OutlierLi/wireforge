/* @wireforge func=0x1B di=00991B01 dir=downlink desc="事件清零扩展载荷" */
typedef struct __attribute__((packed)) {
    uint8_t event_data[2]; /* @desc 事件扩展数据 @hex */
} clear_event_ext_t;
