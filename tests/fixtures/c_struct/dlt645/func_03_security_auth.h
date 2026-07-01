/* @wireforge func=0x03 di=00990301 desc="安全认证扩展载荷" */
typedef struct __attribute__((packed)) {
    uint8_t auth_type; /* @desc 认证类型 @enum 0x01:明文 0x02:密文 */
    uint8_t auth_data[4]; /* @desc 认证数据 @hex */
} security_auth_ext_t;
