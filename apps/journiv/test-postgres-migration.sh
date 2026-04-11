#!/bin/bash
# Test script for PostgreSQL migration validation

set -e

echo "Testing journiv PostgreSQL migration..."

echo "1. Checking current pods..."
kubectl get pods -n journiv

echo ""
echo "2. Validating manifests with kustomize..."
kustomize build apps/journiv --load-restrictor LoadRestrictionsNone >/dev/null && echo "✓ Kustomize build successful"

echo ""
echo "3. Checking ExternalSecret..."
kubectl get externalsecrets -n journiv journiv-secrets -o yaml | grep -A2 "secretKey:"

echo ""
echo "4. Testing PostgreSQL connection (if deployed)..."
if kubectl get statefulsets -n journiv postgres >/dev/null 2>&1; then
	echo "PostgreSQL StatefulSet found, checking pods..."
	if kubectl get pods -n journiv -l app=postgres -o name >/dev/null 2>&1; then
		POSTGRES_POD=$(kubectl get pods -n journiv -l app=postgres -o jsonpath='{.items[0].metadata.name}')

		# Test basic connectivity
		if kubectl exec -n journiv "$POSTGRES_POD" -- pg_isready -U journiv 2>/dev/null; then
			echo "✓ PostgreSQL is ready"
		else
			echo "✗ PostgreSQL is not ready"
		fi
	else
		echo "PostgreSQL pods not running yet"
	fi
else
	echo "PostgreSQL StatefulSet not yet deployed"
fi

echo ""
echo "5. Testing application database connection (if updated)..."
if kubectl get pods -n journiv -l app=journiv-app -o name >/dev/null 2>&1; then
	APP_POD=$(kubectl get pods -n journiv -l app=journiv-app -o jsonpath='{.items[0].metadata.name}')

	# Check environment variables
	echo "Current DATABASE_URL:"
	kubectl exec -n journiv "$APP_POD" -- env | grep DATABASE_URL || echo "DATABASE_URL not set"

	echo "Current DB_DRIVER:"
	kubectl exec -n journiv "$APP_POD" -- env | grep DB_DRIVER || echo "DB_DRIVER not set"
else
	echo "journiv-app not running"
fi

echo ""
echo "6. Checking for common issues..."
echo "   - Checking PVC status..."
kubectl get pvc -n journiv

echo "   - Checking for errors in logs..."
if kubectl get pods -n journiv -l app=journiv-app -o name >/dev/null 2>&1; then
	kubectl logs -n journiv "$APP_POD" --tail=10 | grep -i "error\|fail\|exception" || echo "No errors found in recent logs"
fi

echo ""
echo "Test completed. Review output above for any issues."
