"""Giá trị test vector CPace chép nguyên văn từ draft-irtf-cfrg-cpace-21 (tải bản .txt chính thức
từ IETF datatracker, 2026-10-28), phần Appendix B.1 "Test vector for CPace using group X25519 and
hash SHA-512". Trích tự động bằng script (giải base64 JSON nhúng sẵn trong draft ở B.1.1.1, B.1.9,
B.1.10.1 — không gõ tay) và đối chiếu khớp với bản hex-dump và bản C initializer cùng phần, cả ba
đều khớp byte-exact. Không sửa tay các giá trị này; verify_vectors.py kiểm lại bằng thư viện độc lập.
"""

# B.1.1: calculate_generator(SHA-512, PRS, CI, sid) — generator_string, băm, phần tử trường, generator g.
CPACE_X25519_SHA512_GENERATOR = {
    "H": "SHA-512",
    "H.s_in_bytes": 128,
    "PRS": "50617373776f7264",
    "ZPAD length": 109,
    "DSI": "4350616365323535",
    "CI": "0b415f696e69746961746f720b425f726573706f6e646572",
    "sid": "7e4b4791d6a8ef019b936c79fb7f2c57",
    "generator_string(G.DSI,PRS,CI,sid,H.s_in_bytes)": (
        "0843506163653235350850617373776f72646d0000000000000000000000000000000000000000000000000000000000"
        "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
        "0000000000000000000000000000000000000000000000000000000000000000180b415f696e69746961746f720b425f"
        "726573706f6e646572107e4b4791d6a8ef019b936c79fb7f2c57"
    ),
    "hash generator string": "03998087bdb1a2617bbe25ef5a7c18cd4f84f902328701790958755ee4aed1d3",
    "decoded field element of 255 bits": "03998087bdb1a2617bbe25ef5a7c18cd4f84f902328701790958755ee4aed153",
    "generator g": "d04bf6d41f6a289632a2e929fa29bebd51092512a7829fdde7d314b62f05a73f",
}

# B.1.2-B.1.7: message A/B, K, ISK (initiator/responder và song hành), session id phụ.
CPACE_X25519_SHA512_MESSAGE = {
    "PRS": "50617373776f7264",
    "CI": "0b415f696e69746961746f720b425f726573706f6e646572",
    "sid": "7e4b4791d6a8ef019b936c79fb7f2c57",
    "g": "d04bf6d41f6a289632a2e929fa29bebd51092512a7829fdde7d314b62f05a73f",
    "ya": "21b4f4bd9e64ed355c3eb676a28ebedaf6d8f17bdc365995b319097153044080",
    "ADa": "414461",
    "Ya": "1d13c89278cdadd826f6d8d7f887701430f8380ddc17611cdd6dc989ce0c9f32",
    "yb": "848b0779ff415f0af4ea14df9dd1d3c29ac41d836c7808896c4eba19c51ac40a",
    "ADb": "414462",
    "Yb": "248cccf6d5cdc3646f0ad593f9e6cef4e69d4945f8372e623512ecea32185623",
    "K": "5b067effbdc0b2a0e1d907b21ebb25cfedb96a852179a847c37e43ee71322c6b",
    "ISK_IR": (
        "6e19b875f7a561d6b3ca3dbb9ef42ac55de3e717881018204b8922b4d5e53bb2aa82c300bea7b65d2b671da71922ddf6"
        "472301b79bc270adfa8bf413285f2263"
    ),
    "ISK_SY": (
        "eef745e2f6e7ae2b1a1e53da340e777167a07fe150436648c51fb199c11f3cbabfc683a2b48e1af5881940dc398d375c"
        "95e6b4ae9948a45b8770de0656382be4"
    ),
    "sid_output_ir": (
        "cbc73f62589bbc96ab6a95ec2363df621e93bc3b0cea83ba6b9571d005fa8f5d2d08f7165622777fa484c02a9e6b20a8"
        "4ee2dbebae8c53be757dcfc0eebdeb5f"
    ),
    "sid_output_oc": (
        "3a504e9c7f1f7fa7314861e2c487d13f28566f3043f0ca760d22c4911aca0dd8b1f12a7ad0862eb92d08a76120140412"
        "ae6b8322e99d75cf1d20d8cfde2b40fe"
    ),
}

# B.1.10: G_X25519.scalar_mult_vfy trên điểm bậc thấp (low-order) — u0..ub với vô hướng s cố định;
# q0..qb là kết quả mong đợi (toàn 0 = phải abort). u0,u1,u2,u3,u4,u5,u7 PHẢI kích hoạt abort.
CPACE_X25519_SHA512_LOW_ORDER_SCALAR = "af46e36bf0527c9d3b16154b82465edd62144c0ac1fc5a18506a2244ba449aff"
CPACE_X25519_SHA512_LOW_ORDER_POINTS = [
    {"label": "u0", "u": "0000000000000000000000000000000000000000000000000000000000000000",
     "q": "0000000000000000000000000000000000000000000000000000000000000000", "must_abort": True},
    {"label": "u1", "u": "0100000000000000000000000000000000000000000000000000000000000000",
     "q": "0000000000000000000000000000000000000000000000000000000000000000", "must_abort": True},
    {"label": "u2", "u": "ecffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f",
     "q": "0000000000000000000000000000000000000000000000000000000000000000", "must_abort": True},
    {"label": "u3", "u": "e0eb7a7c3b41b8ae1656e3faf19fc46ada098deb9c32b1fd866205165f49b800",
     "q": "0000000000000000000000000000000000000000000000000000000000000000", "must_abort": True},
    {"label": "u4", "u": "5f9c95bca3508c24b1d0b1559c83ef5b04445cc4581c8e86d8224eddd09f1157",
     "q": "0000000000000000000000000000000000000000000000000000000000000000", "must_abort": True},
    {"label": "u5", "u": "edffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f",
     "q": "0000000000000000000000000000000000000000000000000000000000000000", "must_abort": True},
    {"label": "u6", "u": "daffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
     "q": "d8e2c776bbacd510d09fd9278b7edcd25fc5ae9adfba3b6e040e8d3b71b21806", "must_abort": False},
    {"label": "u7", "u": "eeffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f",
     "q": "0000000000000000000000000000000000000000000000000000000000000000", "must_abort": True},
    {"label": "u8", "u": "dbffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
     "q": "c85c655ebe8be44ba9c0ffde69f2fe10194458d137f09bbff725ce58803cdb38", "must_abort": False},
    {"label": "u9", "u": "d9ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
     "q": "db64dafa9b8fdd136914e61461935fe92aa372cb056314e1231bc4ec12417456", "must_abort": False},
    {"label": "ua", "u": "cdeb7a7c3b41b8ae1656e3faf19fc46ada098deb9c32b1fd866205165f49b880",
     "q": "e062dcd5376d58297be2618c7498f55baa07d7e03184e8aada20bca28888bf7a", "must_abort": False},
    {"label": "ub", "u": "4c9c95bca3508c24b1d0b1559c83ef5b04445cc4581c8e86d8224eddd09f11d7",
     "q": "993c6ad11c4c29da9a56f7691fd0ff8d732e49de6250b6c2e80003ff4629a175", "must_abort": False},
]
