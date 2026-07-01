/* @wireforge func=0x12 di=00991201 dir=uplink desc="读后续数据应答扩展" */
typedef struct __attribute__((packed)) {
    uint8_t follow_data[8]; /* @desc 后续数据块 @hex */
} read_follow_ext_t;
