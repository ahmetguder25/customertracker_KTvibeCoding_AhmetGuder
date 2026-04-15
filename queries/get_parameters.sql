SELECT ParamCode, ParamDescription, ParamValue, ParamValue2, ParamValue3
FROM BOA.ZZZ.Parameter
WHERE ParamType = ? AND LanguageId = ?
ORDER BY CAST(ParamCode AS INTEGER)
