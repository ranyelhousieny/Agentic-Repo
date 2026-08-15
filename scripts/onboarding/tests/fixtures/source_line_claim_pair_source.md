## Part A: Deployment Strategy Options (lines 1-20)

This section covers architectural options for deployment strategy selection.

### Option A: Full Cloud-Native

Pros: Lower operational overhead, faster provisioning.
Cons: Higher cost, vendor lock-in.
Timeline: 3 months.
Effort: Medium.

### Option B: On-Premise Only

Pros: Full control, compliance simplicity.
Cons: Slow provisioning, large capital cost.
Timeline: 6 months.
Effort: High.

### Option C: Hybrid Approach

Combines on-premise and cloud-native components.
Pros: Flexibility, gradual migration.
Cons: Operational complexity.
Timeline: 4-5 months.
Effort: Medium-High.

This section intentionally contains no infrastructure-as-code or networking content.
Pros and cons relate to deployment strategy only.
Lines 1-30 end here.

## Part B: CI/CD and Configuration Management (lines 31-60)

The CI/CD pipeline uses Terraform modules for infrastructure provisioning.

Stage variables for CIAM URL, VPC configuration, and health check strategy are
defined in the Terraform management APIs:
  terraform/apply.sh
  terraform/mgmt-apis/client-management.tf

VPC Links are configured using the same module structure as the management plane.
Health check strategy uses TCP probes on port 443 with a 30-second interval.
State management follows the same remote S3 backend pattern as the control plane.

The VPC Link configuration:
  - Uses existing VPC CIDR blocks from the shared networking module
  - Reuses the same Terraform state management backend (S3 + DynamoDB locking)
  - Health checks match the existing client-management endpoint pattern

### Environment Configuration

Each stage exposes CIAM_URL, VPC_LINK_ID, and HEALTH_CHECK_PATH via stage variables.
