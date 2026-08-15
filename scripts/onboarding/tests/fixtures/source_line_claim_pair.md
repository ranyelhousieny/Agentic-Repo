# source_line_claim_pair.md
#
# Regression fixture for verify_citations.sh SOURCE-line claim-derivation.
#
# This fixture models the structural pattern from CURRENT_DEV_PORTAL_REUSE_ASSESSMENT.md:
# identical surrounding structure (Recommendation bullets + SOURCE line) with a wrong
# citation in Section 1 and a right citation in Section 2.
#
# Wrong citation (Section 1):
#   Claim: Terraform modules / module structure / state management
#   Cites: source_line_claim_pair_source.md lines 1-30 (hybrid-approach OPTIONS prose)
#   Expected: FLAGGED (no Terraform content at lines 1-30)
#
# Right citation (Section 2):
#   Claim: VPC Links / health check strategy / Terraform
#   Cites: source_line_claim_pair_source.md lines 31-60 (CI/CD + Terraform prose)
#   Expected: PASSES (CI/CD prose contains VPC, Terraform, health check content)
#
# Exit behaviour: verify_citations.sh MUST exit non-zero (one fails, one passes).

## API Gateway Reuse Assessment

The following sections assess reuse opportunities from the architecture review.

---

### Section 1: Infrastructure Reuse

The following Terraform infrastructure components can be directly reused:

- Current state of infrastructure tooling and deployment approach
- Team familiarity and existing operational runbooks

**Recommendation:** REUSE Terraform modules from the management plane

- Adapt Terraform modules to the new service context
- Use same module structure for consistency
- Apply same state management conventions across environments

**SOURCE:** source_line_claim_pair_source.md:1-30

---

### Section 2: Networking Reuse

The VPC configuration for the new service follows the existing pattern:

- Existing VPC Link IDs are already configured for the target environments
- Health check endpoints use the same TCP probe strategy as client-management

**Recommendation:** REUSE VPC Links configuration and health check strategy

- Use same VPC Links configuration as management service
- Apply same health check strategy (TCP port 443, 30s interval)
- Reference same stage variables for CIAM URL and VPC configuration

**SOURCE:** source_line_claim_pair_source.md:31-60
