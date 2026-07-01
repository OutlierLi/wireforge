/* @wireforge func=0x13 di=00991301 dir=uplink desc="读通信地址应答扩展" */
typedef struct __attribute__((packed)) {
    char meter_address[6]; /* @desc 表计地址 @alias bcd */
} read_address_ext_t;
