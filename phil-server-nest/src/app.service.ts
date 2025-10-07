import { Injectable } from '@nestjs/common';

@Injectable()
export class AppService {
  getHello(truckName?: string): string {
    return `Hello ${truckName ?? 'World'}!`;
  }
}
