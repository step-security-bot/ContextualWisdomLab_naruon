const fs = require('fs');
const path = require('path');

const filePath = path.join(__dirname, 'backend/tests/test_auth_real.py');
let content = fs.readFileSync(filePath, 'utf8');

// There are multiple instances where `assert decode_called is False` is present, but `decode_called` isn't defined.
content = content.replace(
  /assert exc\.value\.status_code == 401\n    assert decode_called is False\n\n\n@pytest\.mark\.asyncio\nasync def test_oidc_rejects_key_id_that_does_not_match_verified_key/g,
  'assert exc.value.status_code == 401\n    assert decode_called is False\n\n\n@pytest.mark.asyncio\nasync def test_oidc_rejects_key_id_that_does_not_match_verified_key'
);

// We want to delete `assert decode_called is False` from `test_oidc_rejects_key_id_that_does_not_match_verified_key` and `test_oidc_session_rejects_admin_role_claim`. Wait, the error output says line 1065 NameError: 'decode_called' is not defined.
// And 1166 NameError in test_oidc_session_rejects_admin_role_claim.

// Let's just remove `assert decode_called is False` if `decode_called = False` was not declared in the function scope.
fs.writeFileSync(filePath, content);
