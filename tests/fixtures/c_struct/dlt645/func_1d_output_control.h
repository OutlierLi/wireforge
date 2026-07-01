/* @wireforge func=0x1D di=00991D01 dir=downlink desc="多功能端子输出扩展" */
typedef struct __attribute__((packed)) {
    uint8_t output_mode; /* @desc 输出模式 @enum 0x00:关闭 0x01:脉冲 0x02:电平 */
} output_control_ext_t;
