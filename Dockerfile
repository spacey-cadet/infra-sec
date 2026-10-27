# Lambda container image for the Infra Cost Guardian agent.
FROM public.ecr.aws/lambda/python:3.12

COPY requirements.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

COPY agent/ ${LAMBDA_TASK_ROOT}/agent/

CMD ["agent.handler.lambda_handler"]
