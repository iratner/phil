**Controllers**

When using @Controller and defining a endpoint you may include any number of decorators withing the function argument signature.  For instance:

```typescript
@Get()
getItems(@Decorator() arg: string)
```

if the @Decorator is `@Res` or `@Response` you must manage the response using the underlying native platform.  Native platform in this case means an underlying server implementation such as express or fastify.

