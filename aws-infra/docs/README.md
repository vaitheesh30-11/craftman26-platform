# aws-infra/docs — Phase Roadmap

Nine phases. Phase-00 first; the rest respect the deploy order in `../README.md#4`.

| Phase | File                                       | Owner assumption          | Depends on          |
|-------|--------------------------------------------|---------------------------|---------------------|
| 00    | `phase-00-cdk-foundations.txt`             | 1 principal engineer      | –                   |
| 01    | `phase-01-security-stack.txt`              | 1 principal engineer      | 00                  |
| 02    | `phase-02-foundation-stack.txt`            | 1 principal engineer      | 00, 01              |
| 03    | `phase-03-athena-stack.txt`                | 1 principal engineer      | 00, 02              |
| 04    | `phase-04-lambda-stack.txt`                | 1 principal engineer      | 00, 01, 02          |
| 05    | `phase-05-bedrock-stack.txt`               | 1 principal engineer      | 00, 01, 04          |
| 06    | `phase-06-event-stack.txt`                 | 1 principal engineer      | 00, 04              |
| 07    | `phase-07-api-stack.txt`                   | 1 principal engineer      | 00, 04, 05          |
| 08    | `phase-08-crossaccount-stack.txt`          | 1 principal engineer      | 00, 01              |

## Branches

- `feat/aws-infra-foundation`
- `feat/aws-infra-security`
- `feat/aws-infra-foundation-stack`
- `feat/aws-infra-athena`
- `feat/aws-infra-lambda`
- `feat/aws-infra-bedrock`
- `feat/aws-infra-event`
- `feat/aws-infra-api`
- `feat/aws-infra-crossaccount`
